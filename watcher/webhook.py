"""Inbound SMS webhook — opt-in flow for A2P 10DLC compliance.

Deploy as a Railway web service:
    gunicorn watcher.webhook:app

Twilio number → Messaging → "A Message Comes In" webhook → POST /sms
"""

import logging
import os
from datetime import datetime, timezone

from flask import Flask, request, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from watcher.db import get_session_factory
from watcher.models import SmsSubscriber

app = Flask(__name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message copy — keep START / Y / STOP / HELP replies under 160 GSM chars.
# OPT_IN_MESSAGE must match the exact text submitted with your 10DLC campaign.
# ---------------------------------------------------------------------------

OPT_IN_MESSAGE = (
    "Release Watcher: Get automated alerts when tracked artists & authors release new content. "
    "Up to 5 msgs/day. Msg & data rates may apply. Reply HELP for help, STOP to opt out. Reply Y to confirm.\n"
    "Terms: sites.google.com/view/releasewatcher/termsandconditions\n"
    "Privacy: sites.google.com/view/releasewatcher/privacypolicy"
)

CONFIRMATION_MESSAGE = (
    "Release Watcher: You're all set! You'll receive automated alerts when tracked artists "
    "and authors release new content."
)

HELP_MESSAGE = (
    "Release Watcher: Automated new-release alerts. Reply Y to subscribe, STOP to cancel. "
    "Msg&data rates may apply."
)


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------


def _validate_twilio_signature() -> bool:
    """Return True if the request carries a valid Twilio X-Twilio-Signature header."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.warning("TWILIO_AUTH_TOKEN not set — skipping signature validation")
        return True

    validator = RequestValidator(auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")

    # Use the forwarded URL if behind a proxy (Railway sets X-Forwarded-Proto).
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    url = f"{proto}://{host}{request.path}"

    return validator.validate(url, request.form.to_dict(), signature)


# ---------------------------------------------------------------------------
# SMS handler
# ---------------------------------------------------------------------------


@app.route("/sms", methods=["POST"])
def handle_sms():
    if not _validate_twilio_signature():
        logger.warning("Invalid Twilio signature — rejecting request from %s", request.remote_addr)
        return Response("Forbidden", status=403)

    from_number = request.form.get("From", "").strip()
    body = request.form.get("Body", "").strip().upper()

    twiml = MessagingResponse()

    if not from_number:
        return str(twiml), 200, {"Content-Type": "text/xml"}

    session_factory = get_session_factory()
    session = session_factory()
    try:
        subscriber = (
            session.query(SmsSubscriber)
            .filter_by(phone_number=from_number)
            .first()
        )

        if body == "START":
            if not subscriber:
                subscriber = SmsSubscriber(
                    phone_number=from_number,
                    opted_in=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                session.add(subscriber)
                session.commit()
            twiml.message(OPT_IN_MESSAGE)

        elif body in ("Y", "YES"):
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if not subscriber:
                subscriber = SmsSubscriber(
                    phone_number=from_number,
                    opted_in=True,
                    opted_in_at=now,
                    created_at=now,
                )
                session.add(subscriber)
            else:
                subscriber.opted_in = True
                subscriber.opted_in_at = now
                subscriber.opted_out_at = None
            session.commit()
            logger.info("Opted in: %s", from_number)
            twiml.message(CONFIRMATION_MESSAGE)

        elif body == "STOP":
            # Twilio intercepts STOP at the carrier level and sends its own reply.
            # We just mirror the opt-out in our DB — do NOT add a twiml.message() here.
            if subscriber:
                subscriber.opted_in = False
                subscriber.opted_out_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.commit()
                logger.info("Opted out: %s", from_number)

        elif body == "HELP":
            twiml.message(HELP_MESSAGE)

        else:
            logger.info("Unhandled SMS body from %s: %r", from_number, body)

    except Exception:
        logger.exception("Error handling SMS from %s", from_number)
        session.rollback()
    finally:
        session.close()

    return str(twiml), 200, {"Content-Type": "text/xml"}


# ---------------------------------------------------------------------------
# Health check (Railway port probe)
# ---------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
