"""Chapter-edit sentinel node and shared utilities."""

from __future__ import annotations

import re


def _clean_title(line: str) -> str:
    """Strip leading numbering / bullets from a title line."""
    line = re.sub(r'^\d+[\.）\)\uff0e\u3001]\s*', '', line)
    return line.lstrip('-– ').strip()


def chapter_edit_done(state) -> dict:
    """Pass-through sentinel node signalling end of chapter editing.

    父图已改覆盖语义（无 reducer），子图回写同值覆盖无害——
    这里绝不能再返回空列表，否则会把父图的累积列表清空。
    """
    return {}
