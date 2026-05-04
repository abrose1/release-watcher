"""Stretch: Inbound SMS webhook handler.

Validates Twilio signature and processes SMS replies into commands.
"""

import logging

logger = logging.getLogger(__name__)

# Stretch goal — not yet implemented.
# This would be a minimal web service (e.g. Flask or FastAPI) that:
# 1. Validates X-Twilio-Signature header
# 2. Parses the SMS body using judge_sms_reply()
# 3. Updates taste-profile scores and watcher user_overrides
