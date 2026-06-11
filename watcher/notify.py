"""Twilio SMS notifications with quiet hours and error alerting.

WhatsApp send helpers are commented out below — kept as a fallback in case
we need to revert from SMS back to WhatsApp (e.g. Twilio A2P compliance issues).
"""

import logging
import random
from datetime import datetime, timedelta, timezone

import pytz
from twilio.rest import Client as TwilioClient

from watcher.config import get_env, get_quiet_hours_config, get_sms_first_name
from watcher.db import get_session_factory
from watcher.models import NotificationQueue, SmsSubscriber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SMS helpers — commented out; kept for potential future re-enable
# ---------------------------------------------------------------------------

# GREET_GENERIC = (
#     "Hey,",
#     "Hey there,",
#     "Hi,",
#     "Hiya,",
#     "Morning,",
#     "What's good,",
#     "Heads up —",
# )
#
# GREET_WITH_NAME = (
#     "Hey {name},",
#     "Hi {name},",
#     "Morning {name},",
#     "{name}, quick note —",
#     "Hey {name} — FYI:",
# )
#
#
# def _pick_sms_opening() -> str:
#     """Return a casual one-line greeting, sometimes personalized from config."""
#     name = get_sms_first_name()
#     pool: list[str] = list(GREET_GENERIC)
#     if name:
#         pool.extend(template.format(name=name) for template in GREET_WITH_NAME)
#     return random.choice(pool)
#
#
# def _fit_watchlist_core(
#     type_label: str,
#     creator_name: str,
#     title: str,
#     link: str,
#     max_len: int,
# ) -> str:
#     """Body only (no greeting). Fits in max_len; keeps link; may truncate quoted title."""
#     line1 = f"{type_label} \u00b7 {creator_name}"
#     core = f"{line1}\n\"{title}\"\n{link}"
#     if len(core) <= max_len:
#         return core
#
#     framing = len(f'{line1}\n""\n{link}')
#     available = max_len - framing - 3
#     if available > 0:
#         return f'{line1}\n"{title[:available]}..."\n{link}'
#     if len(f"{line1}\n{link}") <= max_len:
#         return f"{line1}\n{link}"
#     return f"{line1}\n{link}"[:max_len]
#
#
# def format_watchlist_sms(
#     creator_name: str,
#     category: str,
#     title: str,
#     release_type: str,
#     link: str,
# ) -> str:
#     """Format a watchlist hit SMS. Casual opener + facts; stays under ~160 GSM chars."""
#     type_label = {
#         "album": "New Album",
#         "single": "New Single",
#         "novel": "New Book",
#         "season": "New Season",
#         "announcement": "Announced",
#     }.get(release_type, "New Release")
#
#     opening = _pick_sms_opening()
#     budget = 160 - len(opening) - 1  # newline between greeting and body
#     if budget <= 0:
#         return (opening[:160])[:160]
#     core = _fit_watchlist_core(type_label, creator_name, title, link, budget)
#     return (f"{opening}\n{core}")[:160]
#
#
# def _fit_discovery_core(
#     category: str,
#     title: str,
#     creator_name: str,
#     reason: str,
#     link: str,
#     max_len: int,
# ) -> str:
#     """Body only (no greeting). Drops reason line when needed; may truncate quoted title."""
#     head = f"Rec \u00b7 {category.title()}"
#     reason_line_full = reason.strip()
#
#     if reason_line_full:
#         msg_wr = f'{head}\n"{title}" by {creator_name}\n{reason_line_full}\n{link}'
#         if len(msg_wr) <= max_len:
#             return msg_wr
#
#     msg_nr = f'{head}\n"{title}" by {creator_name}\n{link}'
#     if len(msg_nr) <= max_len:
#         return msg_nr
#
#     prefix = head + "\n\""
#     suffix = f'" by {creator_name}\n{link}'
#     avail_for_title = max_len - len(prefix) - len(suffix) - 3
#     if avail_for_title > 0:
#         tt = title[:avail_for_title] + "..."
#         cand = prefix + tt + suffix
#         if len(cand) <= max_len:
#             return cand
#     return msg_nr[:max_len]
#
#
# def format_discovery_sms(
#     category: str,
#     title: str,
#     creator_name: str,
#     reason: str,
#     link: str,
# ) -> str:
#     """Format a discovery rec SMS with a casual opener; drops reason line if tight on space."""
#     opening = _pick_sms_opening()
#     budget = 160 - len(opening) - 1  # newline between greeting and body
#     if budget <= 0:
#         return (opening[:160])[:160]
#     core = _fit_discovery_core(category, title, creator_name, reason, link, budget)
#     return (f"{opening}\n{core}")[:160]
#
#
# def send_sms(message_text: str, dry_run: bool = False):
#     """Send an SMS via Twilio. Noop if dry_run=True."""
#     if dry_run:
#         logger.info(f"[DRY RUN] Would send SMS: {message_text}")
#         return
#
#     client = _get_twilio_client()
#     to_number = get_env("YOUR_PHONE_NUMBER")
#     messaging_service_sid = get_env("TWILIO_MESSAGING_SERVICE_SID", required=False)
#
#     payload = {
#         "body": message_text,
#         "to": to_number,
#     }
#     if messaging_service_sid:
#         payload["messaging_service_sid"] = messaging_service_sid
#     else:
#         payload["from_"] = get_env("TWILIO_FROM_NUMBER")
#
#     client.messages.create(**payload)
#     logger.info(f"SMS sent: {message_text[:50]}...")
#
#
# def send_error_sms(job_name: str):
#     """Send a brief error notification SMS."""
#     message = f"[Watcher] {job_name} failed \u2014 check Railway logs"
#     try:
#         send_sms(message, dry_run=False)
#     except Exception as e:
#         logger.error(f"Failed to send error SMS: {e}")

# ---------------------------------------------------------------------------
# SMS send helpers
# ---------------------------------------------------------------------------


def send_sms(message_text: str, to_number: str, dry_run: bool = False):
    """Send an SMS to a specific number via Twilio."""
    if dry_run:
        logger.info("[DRY RUN] Would send SMS to %s: %s", to_number, message_text)
        return

    client = _get_twilio_client()
    messaging_service_sid = get_env("TWILIO_MESSAGING_SERVICE_SID", required=False)
    payload: dict = {"body": message_text, "to": to_number}
    if messaging_service_sid:
        payload["messaging_service_sid"] = messaging_service_sid
    else:
        payload["from_"] = get_env("TWILIO_FROM_NUMBER")

    client.messages.create(**payload)
    logger.info("SMS sent to %s: %s...", to_number, message_text[:50])


def get_opted_in_numbers(session) -> list[str]:
    """Return phone numbers of all currently opted-in subscribers."""
    subscribers = session.query(SmsSubscriber).filter_by(opted_in=True).all()
    return [s.phone_number for s in subscribers]


def send_sms_to_subscribers(message_text: str, dry_run: bool = False):
    """Broadcast an SMS to all opted-in subscribers."""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        numbers = get_opted_in_numbers(session)
        if not numbers:
            logger.warning("No opted-in subscribers — SMS not sent")
            return
        for number in numbers:
            send_sms(message_text, to_number=number, dry_run=dry_run)
    finally:
        session.close()


def send_error_sms(job_name: str):
    """Send a brief error notification SMS to all opted-in subscribers."""
    message = f"[Watcher] {job_name} failed \u2014 check Railway logs"
    try:
        send_sms_to_subscribers(message, dry_run=False)
    except Exception as e:
        logger.error("Failed to send error SMS: %s", e)


# ---------------------------------------------------------------------------
# Message formatting (shared by SMS)
# ---------------------------------------------------------------------------


def format_watchlist_message(
    creator_name: str,
    category: str,
    title: str,
    release_type: str,
    link: str,
) -> str:
    """Format a watchlist hit SMS."""
    type_label = {
        "album": "album",
        "single": "single",
        "novel": "book",
        "season": "season",
        "announcement": "announcement",
    }.get(release_type, "release")

    return f"New {type_label} from {creator_name} — \"{title}\"\n{link}"


def format_discovery_message(
    category: str,
    title: str,
    creator_name: str,
    reason: str,
    link: str,
) -> str:
    """Format a discovery rec SMS."""
    head = f"Rec · {category.title()}"
    parts = [head, f'"{title}" by {creator_name}']
    if reason and reason.strip():
        parts.append(reason.strip())
    parts.append(link)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Twilio client
# ---------------------------------------------------------------------------


def _get_twilio_client() -> TwilioClient:
    return TwilioClient(
        get_env("TWILIO_ACCOUNT_SID"),
        get_env("TWILIO_AUTH_TOKEN"),
    )


# ---------------------------------------------------------------------------
# WhatsApp send helpers — commented out; SMS is the active channel.
# To revert: uncomment below, swap job imports back to send_whatsapp /
# send_error_whatsapp, and update flush_queue to call send_whatsapp.
# ---------------------------------------------------------------------------

# def send_whatsapp(message_text: str, dry_run: bool = False):
#     """Send a WhatsApp message via Twilio. Noop if dry_run=True."""
#     if dry_run:
#         logger.info(f"[DRY RUN] Would send WhatsApp: {message_text}")
#         return
#
#     client = _get_twilio_client()
#     from_number = get_env("TWILIO_FROM_NUMBER")
#     to_number = get_env("YOUR_PHONE_NUMBER")
#
#     client.messages.create(
#         body=message_text,
#         from_=f"whatsapp:{from_number}",
#         to=f"whatsapp:{to_number}",
#     )
#     logger.info(f"WhatsApp sent: {message_text[:50]}...")
#
#
# def send_error_whatsapp(job_name: str):
#     """Send a brief error notification via WhatsApp."""
#     message = f"[Watcher] {job_name} failed \u2014 check Railway logs"
#     try:
#         send_whatsapp(message, dry_run=False)
#     except Exception as e:
#         logger.error(f"Failed to send error WhatsApp: {e}")


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


def is_quiet_hours() -> bool:
    """Check if current local time falls within the quiet window."""
    config = get_quiet_hours_config()
    if not config:
        return False

    tz = pytz.timezone(config.get("timezone", "UTC"))
    now = datetime.now(tz)
    start_str = config.get("start", "22:00")
    end_str = config.get("end", "08:00")

    start_hour, start_min = map(int, start_str.split(":"))
    end_hour, end_min = map(int, end_str.split(":"))

    start_time = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
    end_time = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)

    if start_hour > end_hour:
        if now.hour >= start_hour or now.hour < end_hour:
            return True
        if now.hour == end_hour and now.minute < end_min:
            return True
    else:
        if start_hour <= now.hour < end_hour:
            return True
        if now.hour == end_hour and now.minute < end_min:
            return True

    return False


def next_send_after() -> datetime:
    """Return the next occurrence of quiet_hours.end as a UTC datetime."""
    config = get_quiet_hours_config()
    tz = pytz.timezone(config.get("timezone", "UTC"))
    now = datetime.now(tz)

    end_str = config.get("end", "08:00")
    end_hour, end_min = map(int, end_str.split(":"))

    next_end = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)

    if next_end <= now:
        next_end += timedelta(days=1)

    return next_end.astimezone(pytz.UTC).replace(tzinfo=None)


def flush_queue(dry_run: bool = False):
    """Send all queued notifications past their send_after time.

    Respects max_batch from config — drops lowest priority items if over limit.
    """
    config = get_quiet_hours_config()
    max_batch = config.get("max_batch", 3)

    session_factory = get_session_factory()
    session = session_factory()

    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        pending = (
            session.query(NotificationQueue)
            .filter(
                NotificationQueue.sent_at.is_(None),
                NotificationQueue.send_after <= now,
            )
            .order_by(NotificationQueue.priority.asc())
            .all()
        )

        numbers = get_opted_in_numbers(session)
        if not numbers and not dry_run:
            logger.warning("flush_queue: no opted-in subscribers, nothing to send")

        sent_count = 0
        for item in pending:
            if sent_count >= max_batch:
                logger.info("Max batch reached, dropping: %s...", item.message_text[:30])
                break

            for number in numbers:
                send_sms(item.message_text, to_number=number, dry_run=dry_run)
            if dry_run:
                logger.info("[DRY RUN] Would flush: %s", item.message_text[:50])
            if not dry_run:
                item.sent_at = now
            sent_count += 1

        if not dry_run:
            session.commit()

        logger.info(f"Flushed {sent_count} queued notifications")
    finally:
        session.close()
