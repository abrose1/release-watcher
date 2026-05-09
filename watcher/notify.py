"""Twilio SMS notifications with quiet hours and error alerting."""

import logging
from datetime import datetime, timedelta

import pytz
from twilio.rest import Client as TwilioClient

from watcher.config import get_env, get_quiet_hours_config
from watcher.db import get_session_factory
from watcher.models import NotificationQueue

logger = logging.getLogger(__name__)


def format_watchlist_sms(
    creator_name: str,
    category: str,
    title: str,
    release_type: str,
    link: str,
) -> str:
    """Format a watchlist hit SMS. Keeps under 160 chars where possible."""
    type_label = {
        "album": "New Album",
        "single": "New Single",
        "novel": "New Book",
        "season": "New Season",
        "announcement": "Announced",
    }.get(release_type, "New Release")

    msg = f"{type_label} \u00b7 {creator_name}\n\"{title}\"\n{link}"
    if len(msg) > 160:
        available = 160 - len(f"{type_label} \u00b7 {creator_name}\n\"\"\n{link}") - 3
        if available > 0:
            msg = f"{type_label} \u00b7 {creator_name}\n\"{title[:available]}...\"\n{link}"
        else:
            msg = f"{type_label} \u00b7 {creator_name}\n{link}"
    return msg[:160]


def format_discovery_sms(
    category: str,
    title: str,
    creator_name: str,
    reason: str,
    link: str,
) -> str:
    """Format a discovery rec SMS. Drops reason line if over 160 chars."""
    msg = f"Rec \u00b7 {category.title()}\n\"{title}\" by {creator_name}\n{reason}\n{link}"
    if len(msg) > 160:
        msg = f"Rec \u00b7 {category.title()}\n\"{title}\" by {creator_name}\n{link}"
    return msg[:160]


def _get_twilio_client() -> TwilioClient:
    return TwilioClient(
        get_env("TWILIO_ACCOUNT_SID"),
        get_env("TWILIO_AUTH_TOKEN"),
    )


def send_sms(message_text: str, dry_run: bool = False):
    """Send an SMS via Twilio. Noop if dry_run=True."""
    if dry_run:
        logger.info(f"[DRY RUN] Would send SMS: {message_text}")
        return

    client = _get_twilio_client()
    client.messages.create(
        body=message_text,
        from_=get_env("TWILIO_FROM_NUMBER"),
        to=get_env("YOUR_PHONE_NUMBER"),
    )
    logger.info(f"SMS sent: {message_text[:50]}...")


def send_error_sms(job_name: str):
    """Send a brief error notification SMS."""
    message = f"[Watcher] {job_name} failed \u2014 check Railway logs"
    try:
        send_sms(message, dry_run=False)
    except Exception as e:
        logger.error(f"Failed to send error SMS: {e}")


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
        now = datetime.utcnow()
        pending = (
            session.query(NotificationQueue)
            .filter(
                NotificationQueue.sent_at.is_(None),
                NotificationQueue.send_after <= now,
            )
            .order_by(NotificationQueue.priority.asc())
            .all()
        )

        sent_count = 0
        for item in pending:
            if sent_count >= max_batch:
                logger.info(f"Max batch reached, dropping: {item.message_text[:30]}...")
                break

            send_sms(item.message_text, dry_run=dry_run)
            if not dry_run:
                item.sent_at = now
            sent_count += 1

        if not dry_run:
            session.commit()

        logger.info(f"Flushed {sent_count} queued notifications")
    finally:
        session.close()
