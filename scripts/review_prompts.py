#!/usr/bin/env python3
"""按「题材 × 节点」批量渲染所有 prepare 节点的提示词，供人工 review 质量。

跑法（项目根目录，激活 .venv）：
    python scripts/review_prompts.py [--out DIR] [--genres 通用,玄幻] [--nodes core_theme,arc_outline]

不调 LLM、不需要 API key——只组装最小 fixture NovelState、依次调各 prepare 函数
（走的是真实 prepare_xxx 逻辑，走 build_foundation_context/build_chapter_context/
pack.xxx_prompt 全套），把 system_prompt/context_prompt/task_prompt 拼成完整 messages，
落成 md 文件。

输出结构：
    docs/prompt-review-<今日>/
      通用/
        01_core_theme.md
        02_world_building.md
        ...
      玄幻/
        ...

每份 md 头部有节点/题材/入参摘要，body 是 SystemMessage + HumanMessage 完整文本，
按闸门 A 的 5 行 checklist 走一遍即可对 prompt 质量做人工判定。

设计约束（见 CLAUDE.md）：
- fixture 用最小 3 章样本 + 2 张人物卡 + 1 张势力卡（详见 build_fake_state），
  足够触发所有 prompt 的分支（chapter_plan/scene_beats/entity_cards/volumes/arc/chapter）。
- 不动源码，脚本失败即 fail-loud（Python 层 raise），方便定位 prompt 契约破裂。
- consistency_audit 单独一路（不走 build_prepare_fields）。
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

# src layout 保底：脚本从任意 cwd 跑都能 import noval_workflow
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# 抑制 chapter_context 读磁盘失败告警——脚本用假章号，本来就没落盘章节文件；
# noval_workflow 包内 __init__ 会在 import 时初始化自己的日志,故 basicConfig 无效,
# 必须在 import 之后按 logger 名压制。
logging.basicConfig(level=logging.ERROR)


def _silence_noisy_loggers() -> None:
    """import noval_workflow 之后调用一次,把已知的噪声 logger 抬到 ERROR。"""
    for name in ("noval_workflow.context", "noval_workflow"):
        logging.getLogger(name).setLevel(logging.ERROR)


# ── fixture：最小 NovelState ──────────────────────────────────────────────────


def build_fake_state(genre: str):
    """构造能触发所有节点各分支的最小 NovelState。

    fixture 关键：
    - total_chapters_written = 3：让 chapter_context 走「有近 2 章正文 + 前 1 章摘要」分支，
      即使正文文件读不到也会 fallback 到摘要（context.py 已实现），行为可控。
    - volumes: 1 激活卷（第 1-30 章）+ 1 前瞻草稿卷，覆盖首次/滚动/花名册所有依赖。
    - chapter_plan: 覆盖前 5 章的规划条目，让 chapter/arc/chapter_plan 都能拿到。
    - current_chapter_beats/current_chapter_cast: 挂第 4 章（即 total+1），让 prepare_chapter
      的 beats/cards 注入分支被激活。
    - entity_cards: 主角 + 主要配角 + 反派 + 1 张势力 + 1 张物品（各 role/type 分布）。
    - foreshadowing/phase_summary: 各填一份最小样本，让快照类节点非空。
    """
    from noval_workflow.state import (
        CharacterCard,
        CharacterRole,
        ChapterPlanItem,
        EntityType,
        ItemCard,
        NovelState,
        SimpleEntityCard,
        Volume,
    )

    # 人物/物品/势力卡：覆盖 CharacterCard/ItemCard/SimpleEntityCard 三种变体
    cards = [
        CharacterCard(
            name="林渊",
            type=EntityType.CHARACTER,
            aliases=["少年"],
            summary="山村出身的少年，天生藏着一缕逆天血脉",
            first_appear_chapter=1,
            role=CharacterRole.PROTAGONIST,
            appearance="十六七岁少年，清瘦，左眉有一道浅痕，眼神偏冷",
            speech_style="话不多，但一开口带钉子；生气时反而声音更低",
            personality="表面沉稳克制，骨子里执拗、护短",
            abilities="灵根初显，肉身微强化；已入炼气一层",
            hidden_persona="血脉是上古一支被除名的传承，暗中吸引古老势力窥伺",
            arc_trajectory="开篇被欺凌 → 中期崛起 → 收官担起门派兴废，从少年到扛旗者",
            ability_contract="初始锚点：炼气一层；天花板：结丹前期；隐藏杀手锏：血脉觉醒一击，反噬三日心力",
            motivation="查母亲遗物半张地图指向的旧事",
            current_state="山下小镇客栈，等一位据说识得地图的老者",
            relations="母亲遗物→身世悬念；与苏晚：初识，互相试探；与卓峰：宿敌预定",
        ),
        CharacterCard(
            name="苏晚",
            type=EntityType.CHARACTER,
            aliases=["苏三小姐"],
            summary="世家旁支姑娘，机敏毒舌，暗中调查同一件旧事",
            first_appear_chapter=2,
            role=CharacterRole.MAIN_SUPPORTING,
            appearance="十七八岁少女，青衣束发，眼角有一颗小痣",
            speech_style="健谈毒舌，喜欢反问，笑起来带点挑衅",
            personality="表面轻佻，内里心细如尘",
            abilities="轻功和暗器见长；炼气二层",
            hidden_persona="",
            arc_trajectory="从利用林渊 → 逐步真心，成为最坚定的同盟",
            ability_contract="",
            motivation="查清家族被除名之谜",
            current_state="扮客栈茶博士暗中盯梢",
            relations="与林渊：怀疑却好奇，将来盟友；与家族：貌合神离",
        ),
        CharacterCard(
            name="卓峰",
            type=EntityType.CHARACTER,
            aliases=[],
            summary="邻镇望族少爷，视林渊为眼中钉",
            first_appear_chapter=3,
            role=CharacterRole.FUNCTIONAL_VILLAIN,
            appearance="锦袍男子，浓眉，右手常摩挲一枚玉扳指",
            speech_style="嚣张外放，喜欢自称本少爷",
            personality="骄纵、护短、易怒",
            abilities="炼气三层，家传剑法",
            hidden_persona="",
            arc_trajectory="阶段作用：卷一压制林渊 → 卷二被反制 → 卷末黯然退场",
            ability_contract="",
            motivation="夺回上次被林渊抢走的面子",
            current_state="正带家丁在镇口埋伏",
            relations="与林渊：宿敌；与家族：宠溺过头的独苗",
        ),
        SimpleEntityCard(
            name="青云宗",
            type=EntityType.FACTION,
            aliases=["青云"],
            summary="本地最大修真门派，态度中立偏冷",
            first_appear_chapter=1,
            standing="表面中立，实则监视上古血脉动向",
        ),
        ItemCard(
            name="半张地图",
            type=EntityType.ITEM,
            aliases=["残图"],
            summary="林渊母亲遗物，标记不明的旧禁地入口",
            first_appear_chapter=1,
            effect="拼合完整时可指向禁地",
            rank="宝阶下品",
            owner="林渊",
            status="完好",
        ),
    ]

    volumes = [
        Volume(
            index=1,
            title="第一卷 · 少年入局",
            summary="山村少年被卷入旧事，卷末踏入更大的舞台",
            setup_for_next="母亲遗物半张地图指向禁地入口",
            chapter_start=1,
            planned_end=30,
            actual_end=None,
            status="in_progress",
        ),
        Volume(
            index=2,
            title="第二卷 · 深入禁地",
            summary="循地图入禁地，牵出隐藏势力，身世露端倪",
            setup_for_next="宿敌真身登场",
            chapter_start=0,
            planned_end=0,
            actual_end=None,
            status="planning",
        ),
    ]

    chapter_plan = [
        ChapterPlanItem(
            chapter=1,
            purpose="山村少年被辱不还手，暗中留意奇变",
            key_turn="夜里翻出母亲遗物半张地图",
            ending_hook="地图在月光下浮现一行只有他能读懂的字",
            intensity="铺垫",
        ),
        ChapterPlanItem(
            chapter=2,
            purpose="下山投宿客栈，与苏晚试探性相遇",
            key_turn="苏晚故意撞翻茶盏试探他的反应",
            ending_hook="他把地图塞进腰带，指尖压出一个圈",
            intensity="推进",
        ),
        ChapterPlanItem(
            chapter=3,
            purpose="镇口遭卓峰埋伏，主角首次主动出手",
            key_turn="利用地形和信息差反将一军",
            ending_hook="青云宗执事在人群外冷冷记下他的名字",
            intensity="小转折",
        ),
        ChapterPlanItem(
            chapter=4,
            purpose="镇上一夜，苏晚试探合作意向",
            key_turn="两人交换各自掌握的一半线索",
            ending_hook="苏晚在他床头留下一枚不属于本家族的令牌",
            intensity="推进",
        ),
        ChapterPlanItem(
            chapter=5,
            purpose="拂晓离镇，路遇青云宗弟子暗中跟随",
            key_turn="发现跟踪者，故意留下假线索甩掉",
            ending_hook="他回头一瞥,山道口的令牌被人捡走",
            intensity="推进",
        ),
    ]

    # 章前 scene beats + cast——挂第 4 章（total_chapters_written + 1）
    fake_beats = [
        {
            "id": "b1",
            "scene": "客栈二楼，夜",
            "goal": "试探苏晚是否可信",
            "obstacle": "苏晚绕圈说话",
            "outcome": "两人交换半份线索",
            "cost": "多欠对方一个人情",
            "emotion_arc": "警惕 → 半信",
            "device_tags": ["setup", "buildup"],
            "pacing": "slow",
            "prose_focus": "对话",
            "target_words": 900,
        },
        {
            "id": "b2",
            "scene": "客栈房内，深夜",
            "goal": "独自比对地图与苏晚给的信息",
            "obstacle": "线索指向一处族谱上不存在的地名",
            "outcome": "确认背后另有隐藏势力",
            "cost": "多问下去可能招惹更大的敌人",
            "emotion_arc": "紧张 → 决意",
            "device_tags": ["foreshadow_setup"],
            "pacing": "medium",
            "prose_focus": "心理",
            "target_words": 700,
        },
        {
            "id": "b3",
            "scene": "客栈门外，天色未明",
            "goal": "确认是否有人跟踪",
            "obstacle": "屋檐下的黑影一闪即逝",
            "outcome": "留下一句只有跟踪者才听得懂的话",
            "cost": "暴露自己已察觉",
            "emotion_arc": "冷静 → 锐利",
            "device_tags": ["hook_chapter_end"],
            "pacing": "fast",
            "prose_focus": "动作",
            "target_words": 400,
        },
    ]

    foreshadowing = {
        "pending": [
            {
                "id": "F001",
                "title": "母亲遗物半张地图",
                "planted_chapter": 1,
                "expected_payoff": "卷末揭示禁地位置",
            }
        ],
        "collected": [],
    }

    phase_summary = (
        "【主角基线（第0章）】\n"
        "- 林渊：炼气一层，肉身微强化，无正式功法；\n"
        "- 装备：布衣一套 + 半张地图（贴身）；\n"
        "- 心态：警惕、执拗、不动声色；\n"
        "【环境基线】\n"
        "- 时代：架空东方修真世界，山下小镇为主要活动点；\n"
        "- 势力：青云宗、卓家、林渊母亲背后的隐匿势力（未名）。\n"
    )

    state = NovelState(
        # Phase 0
        novel_name="fixture_novel",
        genre=genre,
        writing_style="干净利落，重画面轻抒情",
        target_audience="18-35 岁网文读者",
        core_tone="冷峻",
        chapter_word_count="3000",
        total_word_count="80 万字",
        has_power_system=True,
        # Phase 1 定稿
        core_theme=(
            "少年因血脉与家族旧事被卷入江湖，在挣扎、失去、抉择中长成担旗人。"
            "作品追问「传承 = 枷锁还是护佑」这一命题。"
        ),
        world_building=(
            "东方修真背景，凡俗与修士两界共存；\n"
            "势力：青云宗（本地最大门派，态度中立）、卓家（地方望族）、林渊母亲背后的隐匿势力；\n"
            "地理：山村→镇→禁地→更大的宗门圈；历史大势：三百年前一场血脉除名之乱余波未消。"
        ),
        power_system=(
            "力量体系分四大阶：炼气 / 筑基 / 结丹 / 元婴，每阶各九层；\n"
            "晋升需灵石与顿悟双条件；跨阶必渡雷劫；\n"
            "血脉传承是隐藏第五轴，绝迹已久，觉醒有反噬。"
        ),
        core_conflicts=(
            "主线冲突：林渊 vs 家族除名旧势力的追猎；\n"
            "副线冲突：主角内心「留家 vs 出走」的抉择；\n"
            "外部冲突：地方望族与门派之间的三方博弈。"
        ),
        overall_outline=(
            "【故事内核】少年因血脉旧事离乡入局，追问「传承是护佑还是枷锁」，情感基调冷峻内敛。\n"
            "【主线动力】追猎与反追猎不断升级，从地方械斗一路推到宗门层级。\n"
            "【暗线与悬念承诺】母亲身份、血脉真源、除名势力的复仇三条暗线交织。\n"
            "【人物弧光大势】林渊从沉默少年到扛旗者；苏晚从利用到真心；卓峰从压制到退场。\n"
            "【结局锚点】开放式偏悲，主角守住传承但失去至亲。"
        ),
        phase_summary=phase_summary,
        volumes=volumes,
        chapter_plan=chapter_plan,
        chapter_plan_planned_upto=5,
        entity_cards=cards,
        # Phase 2 已写 3 章
        current_batch_titles=[
            "山村暗涌",
            "客栈相遇",
            "镇口反击",
            "夜谈交换",
            "拂晓离镇",
        ],
        all_chapter_titles=["山村暗涌", "客栈相遇", "镇口反击"],
        all_chapter_summaries=[
            "林渊在山村被欺凌，夜里翻出母亲遗物半张地图。",
            "他下山投宿客栈，苏晚故意撞翻茶盏试探他的反应。",
            "镇口遭卓峰埋伏，他利用地形反将一军，被青云宗执事记名。",
        ],
        current_chapter_index=3,  # 下一章 index=3 → 第 4 章「夜谈交换」
        total_chapters_written=3,
        continue_writing=True,
        current_arc_outline=_fake_arc_outline(),
        # Phase 2.7：为第 4 章挂 beats + cast
        current_chapter_beats=fake_beats,
        beats_chapter_index=4,
        current_chapter_cast=["林渊", "苏晚"],
        cast_chapter_index=4,
        # 卷级花名册（挂在第 1 卷）
        volume_cast={
            "volume_index": 1,
            "focus": "第一卷主线：少年入局、初识伙伴、卷末踏入更大舞台",
            "returning": [
                {"name": "林渊", "role_in_volume": "本卷主线视角"},
                {"name": "青云宗", "role_in_volume": "中立监视"},
            ],
            "introducing": [
                {"name": "苏晚", "type": "人物"},
                {"name": "卓峰", "type": "人物"},
                {"name": "半张地图", "type": "物品"},
            ],
        },
        volume_cast_index=1,
        # Phase 2.5 快照
        foreshadowing=foreshadowing,
    )
    return state


def _fake_arc_outline() -> str:
    """构造一段 5 章的 arc_outline 假样本——ARC_CHAPTER_FORMAT 8 字段格式。

    scene_beats/chapter/entity_cards 会读它拼 L2；只要含【章节X】分段就能被
    _extract_arc_chapter_block 切出。
    """
    return """【章节1】
0. 本章档位：铺垫
1. 本章核心事件：山村少年被欺凌，夜里翻出母亲遗物半张地图。
2. 人物行动：林渊隐忍旁观，父辈无力反抗；夜里独自在阁楼比对地图痕迹。
3. 情节节点：地图在月光下浮现一行只有他能读懂的字。
4. 节奏&情绪锚点：整章慢，压抑与执拗；网文看点：悬念埋设。
5. 伏笔&线索：新增伏笔 F001 半张地图。
6. 创作锚点：破旧阁楼、油灯、母亲遗物盒。
7. 下章衔接指引：他决定下山投宿镇上客栈探消息。

【章节2】
0. 本章档位：推进
1. 本章核心事件：下山投宿客栈，与苏晚试探性相遇。
2. 人物行动：苏晚故意撞翻茶盏试探；林渊不动声色化解。
3. 情节节点：苏晚从他的反应里判断他并非普通村少年。
4. 节奏&情绪锚点：先松后紧；网文看点：人物互动。
5. 伏笔&线索：暗线苏晚身份成谜。
6. 创作锚点：客栈大堂喧闹、茶博士叫堂、灯影摇曳。
7. 下章衔接指引：卓峰次日会在镇口埋伏。

【章节3】
0. 本章档位：小转折
1. 本章核心事件：镇口遭卓峰埋伏，主角首次主动出手。
2. 人物行动：卓峰带家丁截路挑衅；林渊利用地形和信息差反将一军。
3. 情节节点：青云宗执事在人群外冷冷记下他的名字。
4. 节奏&情绪锚点：中快，紧张里带主动；网文看点：反打小爽点。
5. 伏笔&线索：青云宗视线首次锁定主角。
6. 创作锚点：土墙巷道、家丁刀鞘、执事的记名册。
7. 下章衔接指引：夜里苏晚会带线索找上门。

【章节4】
0. 本章档位：推进
1. 本章核心事件：镇上一夜，苏晚试探合作意向。
2. 人物行动：两人在客栈房中交换各自掌握的一半线索。
3. 情节节点：苏晚在他床头留下一枚不属于本家族的令牌。
4. 节奏&情绪锚点：慢，克制的试探；网文看点：人物关系推进。
5. 伏笔&线索：新伏笔——令牌来源不明。
6. 创作锚点：客栈孤灯、雨声、桌上两杯冷茶。
7. 下章衔接指引：拂晓两人分头行动，苏晚先离镇。

【章节5】
0. 本章档位：推进
1. 本章核心事件：拂晓离镇，路遇青云宗弟子暗中跟随。
2. 人物行动：林渊察觉跟踪，故意留假线索甩掉。
3. 情节节点：他回头一瞥，山道口的令牌被人捡走。
4. 节奏&情绪锚点：中，警觉；网文看点：小悬念。
5. 伏笔&线索：令牌换手，牵引下一段情节。
6. 创作锚点：晨雾、山道、行商的驴车。
7. 下章衔接指引：卷一后半将进入禁地入口周边。
"""


# ── 节点表：题材无关的通用列表 ────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeSpec:
    """一个待渲染的节点。

    name: 输出文件名前缀（不含序号）
    label: 中文可读标签，写进 md 头部
    kind:  "prepare" = 走标准 prepare 函数（返回 {system_prompt, context_prompt, task_prompt}）
           "consistency_audit" = 特殊路径，不走 build_prepare_fields
    fn:    kind=prepare 时，传入 state 返回 dict 的函数
    notes: md 头部对入参的一句话说明（帮助 reviewer 明白 fixture 挂了什么）
    """

    name: str
    label: str
    fn: Callable
    kind: str = "prepare"
    notes: str = ""


def _all_nodes() -> list[NodeSpec]:
    """列出所有会调 LLM 的 prepare 节点——按流程顺序排列（Phase 1 → 2.5 → 2 → 2.7）。"""
    from noval_workflow.chapter_edit_subgraph import _prepare_foreshadowing, _prepare_phase
    from noval_workflow.nodes.arc import prepare_arc_outline
    from noval_workflow.nodes.chapter import prepare_chapter, prepare_titles
    from noval_workflow.nodes.chapter_plan import prepare_chapter_plan
    from noval_workflow.nodes.consistency import audit_consistency
    from noval_workflow.nodes.entity_cards import (
        _prepare_entity_cards,
        _prepare_entity_discover,
    )
    from noval_workflow.nodes.foundation import (
        prepare_character_cards,
        prepare_core_conflicts,
        prepare_core_theme,
        prepare_initial_status,
        prepare_overall_outline,
        prepare_power_system,
        prepare_world_building,
    )
    from noval_workflow.nodes.scene_beats import _prepare_scene_beats
    from noval_workflow.nodes.volume_cast import prepare_volume_cast
    from noval_workflow.nodes.volumes import prepare_volumes

    return [
        NodeSpec("core_theme", "Phase 1 · 核心主题", prepare_core_theme,
                 notes="fixture: 空 core_theme,首次生成"),
        NodeSpec("world_building", "Phase 1 · 世界观", prepare_world_building,
                 notes="fixture: 已有 core_theme,尚无 world_building"),
        NodeSpec("power_system", "Phase 1 · 力量体系", prepare_power_system,
                 notes="fixture: has_power_system=True,已有 world_building"),
        NodeSpec("core_conflicts", "Phase 1 · 核心冲突", prepare_core_conflicts,
                 notes="fixture: 已有主题/世界观/力量体系"),
        NodeSpec("overall_outline", "Phase 1 · 全书战略骨架", prepare_overall_outline,
                 notes="fixture: 前 4 项设定齐全,total_word_count=80 万字"),
        NodeSpec("character_cards", "Phase 1 · 全套人物卡（结构化 JSON）",
                 prepare_character_cards,
                 notes="fixture: 五项基础设定齐全,尚未生成人物卡"),
        NodeSpec("initial_status", "Phase 1 · 第 0 章基线快照",
                 prepare_initial_status,
                 notes="fixture: 人物卡齐,尚未生成 phase_summary(snapshot 类)"),
        NodeSpec("consistency_audit", "Phase 1 收尾 · 设定一致性总审",
                 audit_consistency, kind="consistency_audit",
                 notes="fixture: 五项设定 + 人物卡齐,做跨设定体检"),
        NodeSpec("volumes", "Phase 1.5 · 分卷规划（首次）", prepare_volumes,
                 notes="fixture: volumes 清空(触发首次分卷分支)"),
        NodeSpec("volumes_rolling", "Phase 1.5 · 分卷规划（滚动）", prepare_volumes,
                 notes="fixture: 已有 1 激活卷,触发滚动重规划分支"),
        NodeSpec("volume_cast", "Phase 1.5 · 卷级花名册",
                 prepare_volume_cast,
                 notes="fixture: 第 1 卷激活,已写 3 章"),
        NodeSpec("chapter_plan", "Phase 2.5 · 中景章节规划",
                 prepare_chapter_plan,
                 notes="fixture: 本卷 [1,30] 已规划 5 章,续规划 [4,30]"),
        NodeSpec("arc_outline", "Phase 2.5 · 批级弧线大纲",
                 prepare_arc_outline,
                 notes="fixture: 已写 3 章,下一批第 4-8 章"),
        NodeSpec("titles", "Phase 2 · 本批章节标题", prepare_titles,
                 notes="fixture: 有当前批弧线大纲 + 已写 3 章上下文"),
        NodeSpec("scene_beats", "Phase 2.7 · 章前节拍表",
                 _prepare_scene_beats,
                 notes="fixture: 为第 4 章生成 beats"),
        NodeSpec("entity_cards", "Phase 2.7 · 章前登场实体卡",
                 _prepare_entity_cards,
                 notes="fixture: 第 4 章,已挂 beats"),
        NodeSpec("chapter", "Phase 2 · 章节正文", prepare_chapter,
                 notes="fixture: 第 4 章《夜谈交换》,已挂 beats + 登场卡"),
        NodeSpec("entity_discover", "Phase 2.7 · 章末实体发现",
                 _prepare_entity_discover,
                 notes="fixture: 第 4 章末,读章文补卡 + 更新动态字段"),
        NodeSpec("foreshadowing", "Phase 2.5 · 伏笔台账更新",
                 _prepare_foreshadowing,
                 notes="fixture: 已有 1 条 pending 伏笔,读第 4 章末更新"),
        NodeSpec("phase_summary", "Phase 2.5 · 阶段固化数据更新",
                 _prepare_phase,
                 notes="fixture: 已有第 0 章基线,读第 4 章末更新"),
    ]


# ── volumes 滚动分支 fixture 变造 ─────────────────────────────────────────────


def _mutate_state_for_volumes_first(state):
    """volumes 首次分支：清空 volumes,让 prepare_volumes 走 volumes_prompt 首次生成路径。"""
    import dataclasses

    return dataclasses.replace(state, volumes=[])


# ── 渲染 ──────────────────────────────────────────────────────────────────────


def _render_prepare(spec: NodeSpec, state) -> tuple[str, str, str]:
    """跑一个 prepare 节点,返回 (system, context, task)。"""
    fields = spec.fn(state)
    # build_prepare_fields 的返回契约:三字段都是 str,不存在 fail-loud 时缺字段
    if "system_prompt" not in fields or "task_prompt" not in fields:
        raise RuntimeError(
            f"节点 {spec.name} 的 prepare 返回不含 system_prompt/task_prompt,"
            f"实际 keys: {list(fields.keys())}"
        )
    return (
        fields["system_prompt"],
        fields.get("context_prompt", ""),
        fields["task_prompt"],
    )


def _render_consistency(state) -> tuple[str, str, str]:
    """特化 consistency_audit:不走 build_prepare_fields,自建三层 messages。

    与 audit_consistency 里的组装完全同源(build_system(SystemRole.CONSISTENCY_AUDITOR, ...)
    + CONSISTENCY_AUDIT_PROMPT.format)。
    """
    from noval_workflow.nodes.consistency import _collect_foundation
    from noval_workflow.prompts import CONSISTENCY_AUDIT_PROMPT
    from noval_workflow.prompts.render import SystemRole, build_system

    settings = _collect_foundation(state)
    system = build_system(SystemRole.CONSISTENCY_AUDITOR, "对全部底层设定做一致性总审")
    user = CONSISTENCY_AUDIT_PROMPT.format(draft=settings)
    return system, "", user  # consistency 无 L2 context


def _compose_user(context: str, task: str) -> str:
    """与 render.render_user 同源。"""
    if context:
        return f"【参考资料】\n{context}\n\n【本次任务】\n{task}"
    return task


def _format_md(spec: NodeSpec, genre: str, system: str, context: str, task: str) -> str:
    """生成单份 md,含头部元数据 + SystemMessage + HumanMessage 完整文本。"""
    user = _compose_user(context, task)
    header = [
        f"# {spec.label}",
        "",
        f"- **题材**: {genre}",
        f"- **节点**: `{spec.name}` ({spec.kind})",
        f"- **fixture 说明**: {spec.notes}",
        f"- **system 长度**: {len(system)} 字",
        f"- **context 长度**: {len(context)} 字",
        f"- **task 长度**: {len(task)} 字",
        "",
        "---",
        "",
        "## SystemMessage (L1)",
        "",
        "```",
        system,
        "```",
        "",
        "## HumanMessage (L2 参考资料 + L3 本次任务)",
        "",
        "```",
        user,
        "```",
        "",
    ]
    return "\n".join(header)


# ── 主入口 ────────────────────────────────────────────────────────────────────


@dataclass
class RunConfig:
    out_dir: Path
    genres: list[str]
    nodes: list[str]  # 空 = 全跑
    stop_on_error: bool


def _parse_args() -> RunConfig:
    default_out = _ROOT / "docs" / f"prompt-review-{date.today().isoformat()}"
    # 与前端下拉一致——registry.available_genres() 返回的完整可选题材,
    # 每个都会被前端注入 state.genre,须全部覆盖 review。
    from noval_workflow.prompts.registry import available_genres
    default_genres = available_genres()

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=default_out,
                   help=f"输出根目录（默认: {default_out}）")
    p.add_argument("--genres", type=str, default=",".join(default_genres),
                   help=f"逗号分隔的题材列表（默认: {','.join(default_genres)}）")
    p.add_argument("--nodes", type=str, default="",
                   help="逗号分隔的节点名过滤（默认全跑）")
    p.add_argument("--stop-on-error", action="store_true",
                   help="节点渲染出错即停,默认继续跑并在末尾汇总")
    args = p.parse_args()
    return RunConfig(
        out_dir=args.out,
        genres=[g.strip() for g in args.genres.split(",") if g.strip()],
        nodes=[n.strip() for n in args.nodes.split(",") if n.strip()],
        stop_on_error=args.stop_on_error,
    )


def _sanitize_genre(genre: str) -> str:
    """题材名中的路径分隔符/空格转 _;中文原样保留。"""
    return genre.replace("/", "_").replace(" ", "_")


@dataclass
class Failure:
    genre: str
    node: str
    error: str


def run(config: RunConfig) -> list[Failure]:
    _silence_noisy_loggers()
    all_nodes = _all_nodes()
    # 稳定序号:按「全表位置」而非筛选后序号,让 --nodes 单跑几个时文件名与全跑对得上,方便 diff
    stable_idx = {spec.name: i for i, spec in enumerate(all_nodes, 1)}
    if config.nodes:
        selected = [n for n in all_nodes if n.name in set(config.nodes)]
        if not selected:
            raise SystemExit(f"--nodes 未匹配任何节点: {config.nodes}")
    else:
        selected = all_nodes

    failures: list[Failure] = []
    total_ok = 0

    for genre in config.genres:
        state = build_fake_state(genre)
        genre_dir = config.out_dir / _sanitize_genre(genre)
        genre_dir.mkdir(parents=True, exist_ok=True)

        for spec in selected:
            idx = stable_idx[spec.name]
            try:
                # volumes 首次分支要临时清空 volumes
                if spec.name == "volumes":
                    system, ctx, task = _render_prepare(spec, _mutate_state_for_volumes_first(state))
                elif spec.kind == "consistency_audit":
                    system, ctx, task = _render_consistency(state)
                else:
                    system, ctx, task = _render_prepare(spec, state)
                md = _format_md(spec, genre, system, ctx, task)
                out_file = genre_dir / f"{idx:02d}_{spec.name}.md"
                out_file.write_text(md, encoding="utf-8")
                total_ok += 1
            except Exception as e:  # noqa: BLE001
                failures.append(Failure(genre=genre, node=spec.name, error=repr(e)))
                if config.stop_on_error:
                    raise

        print(f"[{genre}] 已写 {len([n for n in selected if not any(f.genre==genre and f.node==n.name for f in failures)])} / {len(selected)} 份 → {genre_dir}")

    print()
    print(f"✅ 成功: {total_ok} 份")
    if failures:
        print(f"❌ 失败: {len(failures)} 份")
        for f in failures:
            print(f"  - [{f.genre}] {f.node}: {f.error}")
    return failures


def main() -> int:
    config = _parse_args()
    failures = run(config)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
