"""Global configuration constants derived from environment variables."""

from __future__ import annotations

import os

BATCH_SIZE: int = int(os.environ.get("NOVEL_BATCH_SIZE", "5"))

# Context window split: how many of the most-recent chapters to include as full
# text vs. summary-only.  Scales with BATCH_SIZE so the window stays proportional.
#   BATCH_SIZE=5  → FULL_COUNT=2, SUMMARY_COUNT=3
#   BATCH_SIZE=10 → FULL_COUNT=4, SUMMARY_COUNT=6
FULL_COUNT: int = max(1, BATCH_SIZE * 2 // 5)
SUMMARY_COUNT: int = max(1, BATCH_SIZE - FULL_COUNT)
