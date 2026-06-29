"""按小说的提示词覆盖：存储边界（load/apply/save）。

覆盖项粒度为 GenreFlavor 字段（题材差异化扩展面）。存储不入 langgraph state，
而是放在该小说输出目录下的 prompt_overrides.json，与 config.json 同目录、同 key
（安全小说名）。这样每次节点运行时新鲜读取即可即时生效、对历史回放也生效。

设计要点：
- 只接受 GenreFlavor 的已知字段、且值为非空字符串；其余忽略，确保 dataclasses.replace
  安全、不被前端脏数据破坏。
- 这是唯一的存储边界：将来若改用 SQLite / 向量库等，只需替换本文件实现。
"""

from __future__ import annotations

import json
import logging
from dataclasses import fields, replace
from pathlib import Path

from noval_workflow.prompts.base import GenreFlavor

_logger = logging.getLogger(__name__)

OVERRIDE_FILENAME = "prompt_overrides.json"

# GenreFlavor 全部可覆盖字段名（含必填与可选 *_focus）
_FLAVOR_FIELDS: frozenset[str] = frozenset(f.name for f in fields(GenreFlavor))


def _override_path(novel_name: str) -> Path:
    # 惰性 import 规避循环依赖：context -> prompts.__init__ -> registry -> overrides
    from noval_workflow.context import get_output_dir

    return get_output_dir(novel_name) / OVERRIDE_FILENAME


def _clean(overrides: dict) -> dict[str, str]:
    """只保留 GenreFlavor 已知字段、值为非空字符串的项。"""
    return {
        k: v
        for k, v in overrides.items()
        if k in _FLAVOR_FIELDS and isinstance(v, str) and v.strip()
    }


def load_overrides(novel_name: str) -> dict[str, str]:
    """读取该小说的覆盖项；文件缺失/损坏/格式非法时返回 {}。"""
    if not novel_name:
        return {}
    path = _override_path(novel_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        _logger.warning("Failed to read prompt overrides at %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        _logger.warning("Prompt overrides at %s is not a JSON object; ignoring.", path)
        return {}
    return _clean(data)


def apply_overrides(flavor: GenreFlavor, overrides: dict) -> GenreFlavor:
    """把覆盖项合并进题材 flavor；无有效项则原样返回。"""
    clean = _clean(overrides)
    if not clean:
        return flavor
    return replace(flavor, **clean)


def save_overrides(novel_name: str, overrides: dict) -> dict[str, str]:
    """把覆盖项（过滤后）写入该小说的 prompt_overrides.json，返回实际落盘内容。"""
    if not novel_name:
        raise ValueError("save_overrides requires a non-empty novel_name")
    clean = _clean(overrides)
    path = _override_path(novel_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean
