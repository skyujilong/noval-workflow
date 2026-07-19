"""断言「角色登场必须事件驱动、禁止角色介绍流水账」这条约束常驻 prompt。

背景:三层规划(outline / volume / chapter_plan)原本不约束角色登场节奏,规划 LLM 拿到整份
角色花名册后,倾向把主角团一股脑挤在开头几章登场、每章退化成「介绍角色 X」的流水账。现加两条
护栏——base 通用层「配角与伏笔」段的「登场事件驱动」硬约束,以及 comedy_isekai arc_rhythm
的「拉群像必须事件驱动」(保留本题材快速凑队特色,只修流水账)。本测试锁住这两处关键字,
防后续调 prompt 时被误删。
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "src" / "novel_workflow" / "prompts"

# base 通用层(所有题材共用):登场必须事件驱动、禁止角色介绍流水账
REQUIRED_BASE_CAST_INTRO_KEYWORDS = [
    "事件驱动",             # 登场是事件的副产品,不是章目的
    "角色介绍流水账",       # 明确点名要杜绝的坏味道
]

# comedy_isekai 题材层:保留快速凑队特色,但拉群像也要事件驱动
REQUIRED_COMEDY_ISEKAI_CAST_INTRO_KEYWORDS = [
    "拉群像必须事件驱动",   # 针对本题材「反差萌小队集中登场」的修正
    "排队登场",             # 禁止每章只推一个新队友的流水账
]


def test_base_chapter_plan_enforces_event_driven_cast_intro():
    """base 章节规划 prompt 必须含「登场事件驱动 + 反角色介绍流水账」通用护栏。"""
    text = (_PROMPTS_DIR / "base.py").read_text(encoding="utf-8")
    missing = [kw for kw in REQUIRED_BASE_CAST_INTRO_KEYWORDS if kw not in text]
    assert not missing, (
        f"base 登场节奏关键字缺失: {missing}\n"
        f"角色登场必须事件驱动、禁止「介绍角色X」式流水账,这条通用护栏不能被误删。"
    )


def test_comedy_isekai_cast_intro_is_event_driven():
    """comedy_isekai 保留快速凑队,但「拉群像」必须事件驱动、禁止排队登场流水账。"""
    text = (_PROMPTS_DIR / "genres" / "comedy_isekai.py").read_text(encoding="utf-8")
    missing = [kw for kw in REQUIRED_COMEDY_ISEKAI_CAST_INTRO_KEYWORDS if kw not in text]
    assert not missing, (
        f"comedy_isekai 登场节奏关键字缺失: {missing}\n"
        f"本题材可快速凑齐反差萌小队,但每位队友须由事件卷入登场,不许挨个自我介绍的登场秀。"
    )
