"""Daily Tier 1 announcement scan using Brave Search.

Catches release announcements before they hit APIs by searching for each Tier 1
creator (books, music, TV).

Stretch goal: extend this flow (or a sibling job) to surface **concerts / tour
dates** for Tier 1 music acts — needs a reliable source + judge prompts tuned
for tour vs album hype.
"""

import argparse
import asyncio
import hashlib
import logging
import sys
from datetime import datetime, date, timezone

from watcher.config import get_preferences
from watcher.db import get_session_factory
from watcher.models import TrackedCreator, Release, NotificationQueue
from watcher.notify import (
    format_watchlist_message, send_whatsapp, send_error_whatsapp,
    is_quiet_hours, next_send_after,
)
from watcher.sources.brave import BraveSearchClient
from watcher.judge import judge_watchlist_hit

logger = logging.getLogger(__name__)


def compute_announcement_hash(headline: str, url: str) -> str:
    """Compute MD5 hash for announcement deduplication."""
    return hashlib.md5(f"{headline}{url}".encode()).hexdigest()


async def run_announcement_scan(dry_run: bool = False):
    """Run the daily Tier 1 announcement scan."""
    prefs = get_preferences()
    if not prefs.get("tier1_announcement_search", True):
        logger.info("Tier 1 announcement search is disabled in config")
        return

    session_factory = get_session_factory()
    session = session_factory()
    brave = BraveSearchClient()

    try:
        tier1_creators = (
            session.query(TrackedCreator)
            .filter(TrackedCreator.tier == 1)
            .all()
        )

        current_year = date.today().year
        notifications_sent = 0

        for creator in tier1_creators:
            search_results = await brave.search_announcement(
                creator.name, creator.category, current_year
            )

            for result in search_results:
                ann_hash = compute_announcement_hash(result.title, result.url)

                existing = (
                    session.query(Release)
                    .filter_by(announcement_hash=ann_hash)
                    .first()
                )
                if existing:
                    continue

                search_dicts = [
                    {"title": r.title, "url": r.url, "snippet": r.snippet}
                    for r in search_results
                ]

                judge_result = judge_watchlist_hit(
                    creator={"name": creator.name, "tier": creator.tier, "category": creator.category},
                    release_metadata={
                        "title": result.title,
                        "type": "announcement",
                        "date": str(date.today()),
                    },
                    search_results=search_dicts,
                )

                if judge_result.notify:
                    link = judge_result.best_link or result.url
                    message_text = format_watchlist_message(
                        creator_name=creator.name,
                        category=creator.category,
                        title=result.title,
                        release_type="announcement",
                        link=link,
                    )

                    release = Release(
                        tracked_creator_id=creator.id,
                        external_release_id=f"ann_{ann_hash[:16]}",
                        title=result.title,
                        type="announcement",
                        announced_date=date.today(),
                        notified_announced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        source_url=link,
                        announcement_hash=ann_hash,
                    )

                    if not dry_run:
                        session.add(release)
                        session.flush()

                        if is_quiet_hours():
                            queue_item = NotificationQueue(
                                release_id=release.id,
                                message_text=message_text,
                                queued_at=datetime.now(timezone.utc).replace(tzinfo=None),
                                send_after=next_send_after(),
                                priority=10,
                            )
                            session.add(queue_item)
                        else:
                            send_whatsapp(message_text, dry_run=dry_run)

                        notifications_sent += 1
                    else:
                        logger.info(f"[DRY RUN] Would notify: {message_text}")
                        notifications_sent += 1

                    break

        if not dry_run:
            session.commit()

        logger.info(
            f"Announcement scan complete: {len(tier1_creators)} Tier 1 creators checked, "
            f"{notifications_sent} notifications sent"
        )
    finally:
        session.close()


def run(dry_run: bool = False):
    asyncio.run(run_announcement_scan(dry_run=dry_run))


def main():
    parser = argparse.ArgumentParser(description="Daily Tier 1 announcement scan")
    parser.add_argument("--dry-run", action="store_true", help="Log what would be sent without firing Twilio")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        logging.exception(f"Job failed: {e}")
        if not args.dry_run:
            send_error_whatsapp("announcement-scan")
        sys.exit(1)


if __name__ == "__main__":
    main()
