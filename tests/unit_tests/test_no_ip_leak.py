"""断言题材 prompt 文件不含参考作品 IP 特有名词（防止版权/抄袭嫌疑）。

题材文件走「结构范式而非具体元素」原则:反差萌小队公式(神职系×智商缺陷 / 元素系×硬伤限用 /
防御向×命中缺陷)可以照描,但主角名 / 招式专有名 / 参考作品原著名 / 卷名不得出现在 prompt 里,
否则 LLM 会直接照搬人物、招式、书名,存在版权 & 抄袭风险,且限制 LLM 的原创空间。
"""

from __future__ import annotations

from pathlib import Path

# Konosuba(《为美好的世界献上祝福!》)特有名词清单——搞笑异世界题材曾以此为范本,须彻底洗掉。
# 注:"和真"不加入清单——中文里作为普通字组合太常见("和真人"、"和真诚")会误伤,
#    用完整名"佐藤和真"精确定位。
FORBIDDEN_KONOSUBA_TERMS = [
    # 主角三人组姓名
    "阿库娅",
    "佐藤和真",
    "惠惠",
    "达克妮丝",
    # 招式 / 组织专有名词
    "爆裂魔法",
    "红魔族",
    # 原著名 / 卷名(直搬会构成抄袭)
    "为美好的世界献上祝福",
    "为这个中二病献上爆焰",
    "解决这场不像话的战斗",
    "在这冰冻的季节里再死一次",
    "以这只右手偷取宝物",
    # 参考作品简称
    "素晴",
]

# 题材 prompt 目录(相对项目根)
_GENRES_DIR = Path(__file__).parent.parent.parent / "src" / "novel_workflow" / "prompts" / "genres"


def _iter_genre_files() -> list[Path]:
    """收集所有题材 prompt 文件,`__init__.py` / `base.py` 之类元数据文件跳过。"""
    return sorted(
        p for p in _GENRES_DIR.glob("*.py")
        if p.name not in {"__init__.py"}
    )


def test_comedy_isekai_no_konosuba_ip_leak():
    """搞笑异世界题材文件不得包含 Konosuba 原著特有名词。"""
    target = _GENRES_DIR / "comedy_isekai.py"
    text = target.read_text(encoding="utf-8")
    hits = [term for term in FORBIDDEN_KONOSUBA_TERMS if term in text]
    assert not hits, (
        f"发现 Konosuba IP 泄露: {hits}\n"
        f"应改用抽象反差范式 slot(神职系角色 / 元素系天才少女 / 防御向骑士等),"
        f"具体名字 / 招式 / 卷名交由 LLM 原创。"
    )


def test_all_genre_files_no_konosuba_ip_leak():
    """所有题材 prompt 文件(不仅 comedy_isekai)都不得引入 Konosuba IP 名词。

    防止未来新增题材时(如若引入日式轻喜风格分支)再次埋雷。
    """
    for genre_file in _iter_genre_files():
        text = genre_file.read_text(encoding="utf-8")
        hits = [term for term in FORBIDDEN_KONOSUBA_TERMS if term in text]
        assert not hits, f"{genre_file.name} 发现 Konosuba IP 泄露: {hits}"


# ── 节奏关键词护栏 ──────────────────────────────────────────────────────────
# 搞笑异世界题材的核心节奏红线,未来若再次调整 prompt 需保证以下关键词都在。
# 防止误删「7-10 章内爆点」「战斗质感」「允许失败逃跑」「伤亡上限」这些经过多轮蒸馏
# 才定下来的硬约束。
REQUIRED_RHYTHM_KEYWORDS = [
    "7-10 章",          # 爆点频率硬红线
    "爆点章",            # 明确"爆点"概念在 prompt 里
    "战斗质感",          # 战斗不许写薄
    "失败逃跑",          # 允许打不过跑掉作为主角时刻
    "主要小队",          # 伤亡上限的主角保护
    "宿舍暧昧",          # 日常内容池细化(与"欠债+打工"老梗做区分)
    "冒险者公会杂事",    # 日常内容池细化
]


def test_comedy_isekai_rhythm_keywords_present():
    """搞笑异世界题材 prompt 必须包含核心节奏红线关键词。

    这些关键词是节奏调整的锚点——每 7-10 章必爆点、战斗质感落实、允许失败逃跑、
    伤亡上限保护主要角色、日常内容池要覆盖公会杂事+宿舍暧昧——缺一个就意味着
    某条硬约束被误删,LLM 有可能退回到"稀松平常低烈度日常"或"顺利击败魔物"塌陷。
    """
    target = _GENRES_DIR / "comedy_isekai.py"
    text = target.read_text(encoding="utf-8")
    missing = [k for k in REQUIRED_RHYTHM_KEYWORDS if k not in text]
    assert not missing, (
        f"节奏关键词缺失: {missing}\n"
        f"这些关键词是搞笑异世界题材的节奏红线,不得误删。"
    )


# ── arc_rhythm_override 覆盖 base 通用档位护栏 ────────────────────────────
# 搞笑异世界是反爽文题材,爆发上限必须远低于 base 默认 40%。通过 arc_rhythm_override
# 字段整段替换 base 通用档位约束,不能与之并列(否则 LLM 会看到两套占比数字迷惑)。
REQUIRED_ARC_RHYTHM_OVERRIDE_KEYWORDS = [
    "arc_rhythm_override",         # 字段本身存在
    "{BATCH_SIZE}",                # 动态占位——章数由环境变量决定
    "{batch_max_burst}",           # 题材上限占位
    "{batch_min_daily}",           # 题材下限占位
    "≤ 20%",                       # 爆发+大转折 上限(远低于 base 40%)
    "≥ 50%",                       # 铺垫+缓冲+回落+推进 下限
    "日常闹剧为主体",              # 覆盖 base 的定性依据
    "覆盖 base 通用规则",          # 显式声明覆盖关系
]


def test_comedy_isekai_has_arc_rhythm_override():
    """搞笑异世界必须填 arc_rhythm_override 字段以覆盖 base 通用档位约束。

    base 默认 「爆发+转折 ≤ 40%」的上限对本题材过于宽松（反爽文题材应远低于此），
    故本题材必须提供 override 版本整段替换,保证 LLM 拿到的档位红线与题材气质一致。
    """
    target = _GENRES_DIR / "comedy_isekai.py"
    text = target.read_text(encoding="utf-8")
    missing = [k for k in REQUIRED_ARC_RHYTHM_OVERRIDE_KEYWORDS if k not in text]
    assert not missing, (
        f"arc_rhythm_override 关键字缺失: {missing}\n"
        f"本题材是反爽文,必须通过 arc_rhythm_override 覆盖 base 默认 40% 爆发上限,"
        f"降到题材专属 ≤ 20%,且用 {{BATCH_SIZE}} 等动态占位对齐环境变量。"
    )
