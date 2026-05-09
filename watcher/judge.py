"""Anthropic Claude judge for release validation and taste-fit scoring."""

import json
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic

from watcher.config import get_env


class JudgeError(Exception):
    pass


@dataclass
class JudgeResult:
    notify: bool
    reason: str
    best_link: str


@dataclass
class SMSCommand:
    action: str
    creator_name: str | None
    duration_days: int | None


MODEL = "claude-3-5-haiku-20241022"


def _get_client() -> Anthropic:
    return Anthropic(api_key=get_env("ANTHROPIC_API_KEY"))


def judge_watchlist_hit(
    creator: dict[str, Any],
    release_metadata: dict[str, Any],
    search_results: list[dict[str, str]],
) -> JudgeResult:
    """Determine if a detected release is genuine and worth notifying about.

    Args:
        creator: Dict with name, tier, category
        release_metadata: Dict with title, type, date from API
        search_results: Top 3 Brave Search results for context

    Returns:
        JudgeResult with notify decision, reason, and best link
    """
    client = _get_client()

    search_context = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})"
        for r in search_results[:3]
    )

    prompt = f"""You are evaluating whether a detected release is genuine and worth notifying the user about.

Creator: {creator['name']} (Tier {creator['tier']}, Category: {creator['category']})
Release: "{release_metadata.get('title', '')}" (Type: {release_metadata.get('type', 'unknown')}, Date: {release_metadata.get('date', 'unknown')})

Web search context:
{search_context}

Determine:
1. Is this a genuine NEW release (not a remaster, compilation, re-edition, deluxe edition, or re-release under a new title)?
2. Is this a confirmed release/announcement (not just a rumor)?
3. If genuine and confirmed, what is the best article link from the search results?

Respond in JSON format:
{{"notify": true/false, "reason": "brief explanation", "best_link": "url or empty string"}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        text = response.content[0].text
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return JudgeResult(
            notify=bool(result.get("notify", False)),
            reason=result.get("reason", ""),
            best_link=result.get("best_link", ""),
        )
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        raise JudgeError(f"Failed to parse judge response: {e}")


def judge_discovery_candidate(
    candidate: dict[str, Any],
    taste_profile_slice: dict[str, Any],
    search_results: list[dict[str, str]],
) -> JudgeResult:
    """Determine if a discovery candidate fits the user's taste profile.

    Args:
        candidate: Dict with title, creator, category, description
        taste_profile_slice: Top 5 scored creators from taste profile
        search_results: Top 3 Brave Search results for stylistic context

    Returns:
        JudgeResult with notify decision, reason, and best link
    """
    # TODO: pass actual taste profile slice from tracked_creators scores
    client = _get_client()

    search_context = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})"
        for r in search_results[:3]
    )

    top_creators = taste_profile_slice.get("top_creators", [])
    creators_context = ", ".join(top_creators) if top_creators else "Not available"
    film_taste = taste_profile_slice.get("film_taste", "")

    prompt = f"""You are evaluating whether a discovery candidate fits the user's taste profile.

Candidate: "{candidate.get('title', '')}" by {candidate.get('creator', 'Unknown')}
Category: {candidate.get('category', 'unknown')}
Description: {candidate.get('description', 'No description available')}

User's top creators in this category: {creators_context}
Film taste description: {film_taste}

Web search context:
{search_context}

Primary signal is style and genre similarity to the user's top-scored creators. Do NOT cite review scores or ratings as a reason to notify. If the release is worth surfacing, explain specifically what it has in common with what the user already loves.

Respond in JSON format:
{{"notify": true/false, "reason": "brief explanation of taste similarity", "best_link": "url or empty string"}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        text = response.content[0].text
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return JudgeResult(
            notify=bool(result.get("notify", False)),
            reason=result.get("reason", ""),
            best_link=result.get("best_link", ""),
        )
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        raise JudgeError(f"Failed to parse judge response: {e}")


def judge_sms_reply(
    reply_text: str,
    recent_notifications: list[dict[str, Any]],
) -> SMSCommand:
    """Parse an inbound SMS reply into a structured command (stretch goal).

    Args:
        reply_text: The user's SMS reply text
        recent_notifications: Recent notifications sent for context

    Returns:
        SMSCommand with parsed action
    """
    client = _get_client()

    recent_context = "\n".join(
        f"- {n.get('creator', '')} - \"{n.get('title', '')}\" ({n.get('category', '')})"
        for n in recent_notifications[:5]
    )

    prompt = f"""Parse this SMS reply into a command.

User's reply: "{reply_text}"

Recent notifications sent:
{recent_context}

Supported actions: mute, less, more, stop, add, unknown
- "mute [name]" or "mute 30 days" → mute a creator
- "less [name]" → deprioritize a creator
- "more [name]" → boost a creator
- "stop" → stop all notifications
- "add [name]" → add a new creator to track

Respond in JSON format:
{{"action": "action_name", "creator_name": "name or null", "duration_days": number_or_null}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        text = response.content[0].text
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return SMSCommand(
            action=result.get("action", "unknown"),
            creator_name=result.get("creator_name"),
            duration_days=result.get("duration_days"),
        )
    except (json.JSONDecodeError, IndexError, KeyError):
        return SMSCommand(action="unknown", creator_name=None, duration_days=None)
