"""Chapter-edit sentinel node and shared utilities."""

from __future__ import annotations

import re


def _clean_title(line: str) -> str:
    """Strip leading numbering / bullets from a title line."""
    line = re.sub(r'^\d+[\.）\)\uff0e\u3001]\s*', '', line)
    return line.lstrip('-– ').strip()


def chapter_edit_done(state) -> dict:
    """Pass-through sentinel node signalling end of chapter editing.

    Returns empty lists so the parent graph's operator.add reducers
    do not append any spurious values.
    """
    return {"all_chapter_titles": [], "all_chapter_summaries": []}
