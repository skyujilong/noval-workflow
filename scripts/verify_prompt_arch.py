#!/usr/bin/env python3
"""P0 验收脚本：验证 core_theme 步骤的三层 prompt 重构。

跑法（项目根目录，激活 .venv）：
    python scripts/verify_prompt_arch.py

它不调 LLM、不需要 ARK_API_KEY--只组装 messages 并打印 + 自动检查。
对比「旧路径（build_foundation_context 全量塞 system + core_theme_prompt 进 user）」
与「新路径（core_theme_request -> render 三层：L1 system / L2 context / L3 task）」，
自动检查分层是否成立：身份只在 L1、资料移到 L2、硬契约进 L1、无双注。

退出码 0 = 全部检查 PASS；非 0 = 有 FAIL。
"""

from __future__ import annotations

import sys
from pathlib import Path

# src layout 保底：脚本从任意 cwd 跑都能 import noval_workflow
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402
from noval_workflow.context import build_foundation_context  # noqa: E402
from noval_workflow.prompts import get_prompt_pack  # noqa: E402
from noval_workflow.prompts.render import HARD_CONTRACTS, render  # noqa: E402
from noval_workflow.state import (  # noqa: E402
    CharacterCard,
    CharacterRole,
    EntityType,
    NovelState,
)

# ── 资料段头白名单（来自 llm.py _SYSTEM_CONTEXT_TOP_SECTIONS，代表"设定/台账资料"）
# 新 system 不应出现任何这些【】段头--它们属于 L2 资料。
_RESOURCE_SECTION_HEADERS = (
    "【世界观设定】",
    "【力量体系（本作已定稿，创作时必须严格遵循）】",
    "【核心冲突】",
    "【整体大纲与结局】",
    "【人物档案】",
    "【本批章节弧线大纲】",
    "【伏笔台账（最新）】",
    "【阶段固化数据（最新）】",
    "【登场实体卡·装备/物品",
)

# 资料正文探针：取 mock state 各设定字段的独特短语。若出现在新 system，说明资料血肉泄露。
# （"【核心主题与立意】"既是资料段头又是任务契约产物名，用段头无法区分，改用正文探针。）
_RESOURCE_PROBES = (
    "病毒爆发三年后的废土世界",  # world_building
    "体能强化 / 感知扩展",  # power_system
    "人与丧尸的生存冲突",  # core_conflicts
    "末世求生小队队长",  # entity_cards
    "棒球棍、压缩饼干",  # phase_summary
    "主角身世之谜",  # foreshadowing
    "寻找失散的妹妹",  # overall_outline
    "守住人性的底线",  # core_theme
)

# generic 题材 system_identity 的特征短语（用来核验"身份在 L1 / 不在 user"）
_IDENTITY_MARKER = "深耕日系轻小说"


def _divider(title: str) -> None:
    print(f"\n{'＝' * 8} {title} {'＝' * 8}")


def build_mock_state() -> NovelState:
    """构造一个"设定已填满"的 NovelState，模拟设定就绪后调用 core_theme_request。

    用满设定是为了清晰展示分层：旧路径会把全部设定塞 system（臃肿），
    新路径把设定移到 L2、system 保持瘦固定。
    """
    state = NovelState()
    # Phase 0 基础参数
    state.novel_name = "末世求生录"
    state.genre = "通用"
    state.writing_style = "硬核求生"
    state.target_audience = "18-35 男性"
    state.core_tone = "紧张压抑"
    state.chapter_word_count = "3000"
    state.total_word_count = "50万字"
    # Phase 1 foundation 设定（填满，模拟设定已就绪）
    state.core_theme = "在末世废土中，普通人如何守住人性的底线，比活下去更难。"
    state.world_building = (
        "病毒爆发三年后的废土世界，城市废墟化，幸存者聚居地散布，资源极度匮乏。"
    )
    state.power_system = (
        "异能体系：体能强化 / 感知扩展 / 精神控制三系，分初/中/高三阶。"
    )
    state.core_conflicts = (
        "人与丧尸的生存冲突；人与人争夺资源的冲突；主角与自身软肋的内在冲突。"
    )
    state.overall_outline = (
        "【故事内核】少年在末世求生。【主线动力】寻找失散的妹妹。"
        "【暗线与悬念承诺】病毒源头之谜。【人物弧光】从冷漠到重情。【结局锚点】开放结局。"
    )
    state.entity_cards = [
        CharacterCard(
            name="林默",
            type=EntityType.CHARACTER,
            role=CharacterRole.PROTAGONIST,
            summary="末世求生小队队长",
            appearance="瘦高少年，眼神警觉",
            speech_style="寡言简短",
            personality="冷静务实，重情义",
            abilities="体能强化系异能初阶",
        )
    ]
    state.foreshadowing = {
        "pending": [{"id": "F1", "name": "主角身世之谜", "chapter": 1}],
        "collected": [],
    }
    state.phase_summary = "主角等级：1 阶；持有：棒球棍、压缩饼干×2"
    # chapter 类 prepare 需要的额外状态
    state.current_batch_titles = ["末世降临", "初次相遇", "危机四伏"]
    state.current_arc_outline = "【章节1】本章核心事件：主角醒来发现末世。"
    from noval_workflow.state import Volume

    state.volumes = [
        Volume(
            index=1,
            title="第一卷·末世",
            summary="主角末世求生",
            setup_for_next="妹妹线索",
            chapter_start=1,
            planned_end=30,
            status="in_progress",
        )
    ]
    return state


def assemble_old_path(state: NovelState) -> tuple[str, str]:
    """旧路径：build_foundation_context(state) 进 system + core_theme_prompt 进 user。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    old_system = build_foundation_context(state)
    old_user = pack.core_theme_prompt
    return old_system, old_user


def assemble_new_path(state: NovelState):
    """新路径：core_theme_request(state) -> render() 三层 messages。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    req = pack.core_theme_request(state)
    msgs = render(req)
    return req, msgs


def run_checks(
    old_system: str,
    old_user: str,
    req,
    msgs,
) -> list[tuple[str, bool, str]]:
    """逐项检查，返回 (检查名, 通过?, 说明) 列表。"""
    new_system = req.system
    new_context = "\n\n".join(s.body for s in req.context if s.body)
    new_user = msgs[1].content

    checks: list[tuple[str, bool, str]] = []

    # C1 新 system 不含资料正文血肉（资料移到 L2；任务契约里的产物名不算泄露）
    leaked = [p for p in _RESOURCE_PROBES if p in new_system]
    checks.append(
        (
            "C1 新 system 不含资料正文",
            not leaked,
            f"泄露探针: {leaked}" if leaked else "无资料血肉泄露进 system",
        )
    )

    # C2 身份在新 system（身份进 L1）
    has_id_in_system = _IDENTITY_MARKER in new_system
    checks.append(
        (
            "C2 身份进 L1 system",
            has_id_in_system,
            "身份在 system" if has_id_in_system else "身份缺失于 system",
        )
    )

    # C3 身份不在新 user（无双注）--最关键
    id_in_user = _IDENTITY_MARKER in new_user
    checks.append(
        (
            "C3 身份不在 L2/L3（无双注）",
            not id_in_user,
            "身份未重复注入 user" if not id_in_user else "身份在 user 重复出现",
        )
    )

    # C4 四条硬契约名都在新 system
    missing = [c.name for c in HARD_CONTRACTS if c.name not in new_system]
    checks.append(
        (
            "C4 四条硬契约进 L1",
            not missing,
            f"缺失: {missing}"
            if missing
            else "反降智/跨设定一致/因果闭环/强延展留白 齐全",
        )
    )

    # C5 优先级约定在新 system
    has_priority = "历史整改要点" in new_system and "硬契约" in new_system
    checks.append(
        (
            "C5 优先级约定进 L1",
            has_priority,
            "含历史整改要点+硬契约裁决框架" if has_priority else "优先级约定缺失",
        )
    )

    # C6 新 L2 含资料段头（资料确实移到 L2）
    l2_has_resource = any(h in new_context for h in _RESOURCE_SECTION_HEADERS)
    checks.append(
        (
            "C6 资料移到 L2",
            l2_has_resource,
            "L2 含设定段头" if l2_has_resource else "L2 缺资料段头",
        )
    )

    # C7 render 结构：1 SystemMessage + 1 HumanMessage
    struct_ok = (
        len(msgs) == 2
        and isinstance(msgs[0], SystemMessage)
        and isinstance(msgs[1], HumanMessage)
    )
    checks.append(
        (
            "C7 render 结构 1+1",
            struct_ok,
            f"len={len(msgs)}, types={[type(m).__name__ for m in msgs]}",
        )
    )

    # C8 新 system 瘦于旧 system（满设定场景：旧含全部设定，新固定~340字）
    sys_shrunk = len(new_system) < len(old_system)
    detail_c8 = (
        f"新 {len(new_system)} 字 < 旧 {len(old_system)} 字"
        if sys_shrunk
        else f"新 {len(new_system)} 字 >= 旧 {len(old_system)} 字"
    )
    checks.append(("C8 新 system 瘦于旧", sys_shrunk, detail_c8))

    return checks


def run_prepare_checks(state: NovelState) -> list[tuple[str, bool, str]]:
    """遍历 7 个 foundation prepare，检查每个产出三层且无双注/资料在 L2。

    每个 prepare 返回 dict 含 system_prompt(L1)/context_prompt(L2)/task_prompt(L3)。
    检查：身份只在 L1 不在 L3（无双注）、资料在 L2 不在 L1、硬契约在 L1、三字段非空。
    """
    from noval_workflow.nodes.foundation import (
        prepare_character_cards,
        prepare_core_conflicts,
        prepare_core_theme,
        prepare_initial_status,
        prepare_overall_outline,
        prepare_power_system,
        prepare_world_building,
    )

    prepares = [
        ("core_theme", prepare_core_theme),
        ("world_building", prepare_world_building),
        ("power_system", prepare_power_system),
        ("core_conflicts", prepare_core_conflicts),
        ("overall_outline", prepare_overall_outline),
        ("character_cards", prepare_character_cards),
        ("initial_status", prepare_initial_status),
    ]
    checks: list[tuple[str, bool, str]] = []
    for name, fn in prepares:
        result = fn(state)
        system = result.get("system_prompt", "")
        context = result.get("context_prompt", "")
        task = result.get("task_prompt", "")
        review_type = result.get("review_type", "")

        # 字段齐全
        fields_ok = bool(system and task and review_type)
        checks.append(
            (
                f"F-{name} 三字段齐全",
                fields_ok,
                f"review_type={review_type}" if fields_ok else "缺字段",
            )
        )

        # 身份不在 task（无双注）--initial_status 是 snapshot 身份，用"数据维护员"探针
        if name == "initial_status":
            id_probe = "数据维护员"
            id_in_system = id_probe in system
        else:
            id_probe = _IDENTITY_MARKER
            id_in_system = id_probe in system
        id_in_task = id_probe in task
        checks.append(
            (
                f"F-{name} 身份无双注",
                id_in_system and not id_in_task,
                f"在L1={id_in_system} 在L3={id_in_task}",
            )
        )

        # 资料血肉不在 system
        leaked = [p for p in _RESOURCE_PROBES if p in system]
        checks.append(
            (f"F-{name} 资料不在L1", not leaked, f"泄露:{leaked}" if leaked else "干净")
        )

        # 硬契约在 system（全部 prepare 守硬契约）
        missing = [c.name for c in HARD_CONTRACTS if c.name not in system]
        checks.append(
            (
                f"F-{name} 硬契约在L1",
                not missing,
                "齐全" if not missing else f"缺{missing}",
            )
        )

        # 资料在 L2（context_prompt 非空且含设定段头）--initial_status exclude_snapshots，
        # 但仍含世界观/力量体系/人物档案（deep_character_view），故同样检查
        l2_has = any(h in context for h in _RESOURCE_SECTION_HEADERS)
        checks.append((f"F-{name} 资料在L2", l2_has, "有" if l2_has else "缺"))

    # chapter 类 prepare（与 foundation 同模式检查，但部分需更完整 state）
    from noval_workflow.nodes.arc import prepare_arc_outline
    from noval_workflow.nodes.chapter import prepare_chapter, prepare_titles
    from noval_workflow.nodes.chapter_plan import prepare_chapter_plan
    from noval_workflow.nodes.entity_cards import (
        _prepare_entity_cards,
        _prepare_entity_discover,
    )
    from noval_workflow.nodes.scene_beats import _prepare_scene_beats
    from noval_workflow.nodes.volume_cast import prepare_volume_cast
    from noval_workflow.nodes.volumes import prepare_volumes

    chapter_prepares = [
        ("titles", prepare_titles),
        ("chapter", prepare_chapter),
        ("arc_outline", prepare_arc_outline),
        ("chapter_plan", prepare_chapter_plan),
        ("scene_beats", _prepare_scene_beats),
        ("volumes", prepare_volumes),
        ("volume_cast", prepare_volume_cast),
        ("entity_cards", _prepare_entity_cards),
        ("entity_discover", _prepare_entity_discover),
    ]
    for name, fn in chapter_prepares:
        try:
            result = fn(state)
        except Exception as exc:  # noqa: BLE001 - 容错：部分 prepare 需特定 state，失败标 FAIL 不中断
            checks.append((f"F-{name} prepare 可运行", False, f"异常: {exc!r}"))
            continue
        system = result.get("system_prompt", "")
        task = result.get("task_prompt", "")
        review_type = result.get("review_type", "")

        fields_ok = bool(system and task and review_type)
        checks.append(
            (
                f"F-{name} 三字段齐全",
                fields_ok,
                f"review_type={review_type}" if fields_ok else "缺字段",
            )
        )

        id_in_system = _IDENTITY_MARKER in system
        id_in_task = _IDENTITY_MARKER in task
        checks.append(
            (
                f"F-{name} 身份无双注",
                id_in_system and not id_in_task,
                f"在L1={id_in_system} 在L3={id_in_task}",
            )
        )

        leaked = [p for p in _RESOURCE_PROBES if p in system]
        checks.append(
            (f"F-{name} 资料不在L1", not leaked, f"泄露:{leaked}" if leaked else "干净")
        )

        missing = [c.name for c in HARD_CONTRACTS if c.name not in system]
        checks.append(
            (
                f"F-{name} 硬契约在L1",
                not missing,
                "齐全" if not missing else f"缺{missing}",
            )
        )

    # snapshot 类 prepare（foreshadowing/phase）：身份=数据维护员，prev 在 task 不在 L2
    from noval_workflow.chapter_edit_subgraph import (
        _prepare_foreshadowing,
        _prepare_phase,
    )

    snapshot_prepares = [
        ("foreshadowing", _prepare_foreshadowing, "上次伏笔台账"),
        ("phase", _prepare_phase, "上次阶段固化数据"),
    ]
    for name, fn, prev_marker in snapshot_prepares:
        try:
            result = fn(state)
        except Exception as exc:  # noqa: BLE001
            checks.append((f"F-{name} prepare 可运行", False, f"异常: {exc!r}"))
            continue
        system = result.get("system_prompt", "")
        task = result.get("task_prompt", "")

        maintainer_in_system = "数据维护员" in system
        checks.append(
            (
                f"F-{name} 数据维护员身份",
                maintainer_in_system,
                "在L1" if maintainer_in_system else "缺失",
            )
        )

        missing = [c.name for c in HARD_CONTRACTS if c.name not in system]
        checks.append(
            (
                f"F-{name} 硬契约在L1",
                not missing,
                "齐全" if not missing else f"缺{missing}",
            )
        )

        prev_in_task = prev_marker in task
        checks.append(
            (
                f"F-{name} prev在task",
                prev_in_task,
                "在L3" if prev_in_task else "task无prev（可能state空）",
            )
        )

    return checks


# ── 步骤 09：generate / llm_self_review 拼装 + 独立 LLM 点硬契约 ──────────────────
#
# 用 mock LLM（记录 invoke 收到的 messages）验证三件事：
# 1) generate 首轮拼装 = [SystemMessage(state.system_prompt), HumanMessage(render_user(L2, L3))]，
#    system 含身份+硬契约，user 含【参考资料】+【本次任务】--证明 generate 走单一 render、无分支。
# 2) llm_self_review 的 user 含【参考资料】L2--旧路径 review_prompt 不含资料导致自审丢资料，
#    重构后 render_user(context, review_prompt) 让自审也能看到设定（跨设定一致性审核成立）。
# 3) 独立 LLM 点（audit_consistency / entity_cards_prune_analyze / foreshadow_prune_analyze）
#    的 system 含全部硬契约--证明它们也走 build_system、守 L1 底线，而非残留内联 system。
#    chapter_plan_edit 三处私有 LLM 点做 source 审计（build_system/render_user 接线），
#    因其需重组装 ChapterPlanEditSubState、ROI 低于运行时验证。


class _RecordingLLM:
    """记录每次 invoke 的 messages，返回固定 content。供 mock get_llm 使用。"""

    def __init__(self, recorder: list, key: str, content: str) -> None:
        self.recorder = recorder
        self.key = key
        self.content = content

    def invoke(self, messages):
        self.recorder.append((self.key, list(messages)))
        return AIMessage(content=self.content)


def _patch_llm(module, recorder: list, key: str, content: str):
    """把 module.get_llm 替换为返回 _RecordingLLM 的桩；返回原值便于恢复。"""
    original = getattr(module, "get_llm")
    module.get_llm = lambda *a, **k: _RecordingLLM(recorder, key, content)
    return original


def run_generate_self_review_checks(state: NovelState) -> list[tuple[str, bool, str]]:
    """步骤 09 验收：generate/自审拼装 + 独立 LLM 点硬契约。"""
    import json

    from noval_workflow import subgraph as sg
    from noval_workflow.nodes import consistency
    from noval_workflow.entity_cards_prune_subgraph import entity_cards_prune_analyze
    from noval_workflow.foreshadow_prune_subgraph import foreshadow_prune_analyze
    from noval_workflow.prompts import get_prompt_pack
    from noval_workflow.prompts.render import build_prepare_fields
    from noval_workflow.state import ReviewSubState

    checks: list[tuple[str, bool, str]] = []
    pack = get_prompt_pack(state.genre, state.novel_name)

    # 用 core_theme（创作类、自审未关闭）构造 ReviewSubState，触发真实 generate/自审路径
    fields = build_prepare_fields(
        system_identity=pack.flavor.system_identity,
        task_contract="提炼核心主题与立意",
        context="【世界观设定】\n病毒爆发三年后的废土世界",
        task="请输出核心主题。",
    )
    rs = ReviewSubState(
        review_type="core_theme",
        system_prompt=fields["system_prompt"],
        context_prompt=fields["context_prompt"],
        task_prompt=fields["task_prompt"],
        current_draft="（草稿占位）核心主题：守住人性底线。",
    )

    # ── 1) generate 首轮拼装 ──
    recorder: list = []
    orig_sg = _patch_llm(sg, recorder, "generate", "占位草稿")
    try:
        sg.generate(rs)
    finally:
        sg.get_llm = orig_sg

    gen_msgs = [m for k, m in recorder if k == "generate"]
    gen_ok = bool(gen_msgs) and len(gen_msgs[0]) == 2
    checks.append(
        (
            "G-generate 双消息",
            gen_ok,
            f"messages={len(gen_msgs[0]) if gen_msgs else 0}" if gen_msgs else "未触发 generate",
        )
    )
    if gen_msgs:
        gm = gen_msgs[0]
        sys_is_l1 = str(gm[0].content) == rs.system_prompt
        checks.append(
            (
                "G-generate system=L1(state.system_prompt)",
                sys_is_l1,
                "system 直接用 state.system_prompt" if sys_is_l1 else "system 与 L1 不一致",
            )
        )
        user_text = str(gm[1].content)
        user_has_l2 = "【参考资料】" in user_text
        user_has_l3 = "【本次任务】" in user_text
        checks.append(
            (
                "G-generate user 含 L2 资料",
                user_has_l2,
                "render_user 拼入【参考资料】" if user_has_l2 else "user 缺【参考资料】",
            )
        )
        checks.append(
            (
                "G-generate user 含 L3 任务",
                user_has_l3,
                "render_user 拼入【本次任务】" if user_has_l3 else "user 缺【本次任务】",
            )
        )
        # system 含身份 + 全部硬契约（generate 不内联拼身份/设定，复用 prepare 的 L1）
        sys_text = str(gm[0].content)
        gen_id_ok = _IDENTITY_MARKER in sys_text
        gen_missing = [c.name for c in HARD_CONTRACTS if c.name not in sys_text]
        checks.append(
            (
                "G-generate system 含身份",
                gen_id_ok,
                "身份在 L1" if gen_id_ok else "system 缺身份",
            )
        )
        checks.append(
            (
                "G-generate system 含硬契约",
                not gen_missing,
                "齐全" if not gen_missing else f"缺{gen_missing}",
            )
        )

    # ── 2) llm_self_review 拼装（关键：自审能看到 L2）──
    recorder2: list = []
    orig_sg2 = _patch_llm(sg, recorder2, "self_review", "无问题")
    try:
        sg.llm_self_review(rs)
    finally:
        sg.get_llm = orig_sg2

    sr_msgs = [m for k, m in recorder2 if k == "self_review"]
    sr_ok = bool(sr_msgs) and len(sr_msgs[0]) == 2
    checks.append(
        (
            "G-self_review 双消息",
            sr_ok,
            f"messages={len(sr_msgs[0]) if sr_msgs else 0}" if sr_msgs else "未触发自审（可能被关闭）",
        )
    )
    if sr_msgs:
        sr_user = str(sr_msgs[0][1].content)
        sr_has_l2 = "【参考资料】" in sr_user
        # 旧路径 review_prompt 不含 L2，自审看不到设定 -> 跨设定一致性审核失效。
        # 此处断言 L2 经 render_user 拼入自审 user，是本重构的关键收益之一。
        checks.append(
            (
                "G-self_review user 含 L2（解决丢资料）",
                sr_has_l2,
                "自审能看到设定" if sr_has_l2 else "自审仍丢资料",
            )
        )
        sr_sys_is_l1 = str(sr_msgs[0][0].content) == rs.system_prompt
        checks.append(
            (
                "G-self_review system=L1",
                sr_sys_is_l1,
                "自审复用 generate 的 L1" if sr_sys_is_l1 else "system 与 L1 不一致",
            )
        )

    # ── 3) 独立 LLM 点：system 含全部硬契约 ──
    def _assert_indep_system(rec, key, label):
        msgs = [m for k, m in rec if k == key]
        if not msgs:
            checks.append((f"G-{label} 触发 LLM", False, "未记录到 messages"))
            return
        sys_text = str(msgs[0][0].content)
        missing = [c.name for c in HARD_CONTRACTS if c.name not in sys_text]
        checks.append(
            (
                f"G-{label} system 含硬契约",
                not missing,
                "齐全" if not missing else f"缺{missing}",
            )
        )

    # audit_consistency（创作类 text，返回"无问题"）
    rec_c: list = []
    orig_c = _patch_llm(consistency, rec_c, "consistency_audit", "无问题")
    try:
        consistency.audit_consistency(state)
    finally:
        consistency.get_llm = orig_c
    _assert_indep_system(rec_c, "consistency_audit", "consistency_audit")

    # entity_cards_prune_analyze（invoke_json kind=dict，需返回合法 JSON 对象）
    rec_ec: list = []
    fake_json = json.dumps(
        {"to_delete": [], "card_count": 1, "suggestion": "无"}, ensure_ascii=False
    )
    import noval_workflow.entity_cards_prune_subgraph as ec_mod

    orig_ec = _patch_llm(ec_mod, rec_ec, "entity_cards_prune", fake_json)
    try:
        entity_cards_prune_analyze(state)
    finally:
        ec_mod.get_llm = orig_ec
    _assert_indep_system(rec_ec, "entity_cards_prune", "entity_cards_prune")

    # foreshadow_prune_analyze（需 current_draft 为合法伏笔 JSON）
    rec_f: list = []
    state.current_draft = json.dumps(state.foreshadowing, ensure_ascii=False)
    import noval_workflow.foreshadow_prune_subgraph as f_mod

    orig_f = _patch_llm(f_mod, rec_f, "foreshadow_prune", fake_json)
    try:
        foreshadow_prune_analyze(state)
    finally:
        f_mod.get_llm = orig_f
    _assert_indep_system(rec_f, "foreshadow_prune", "foreshadow_prune")

    # chapter_plan_edit 三处私有 LLM 点：source 审计（build_system/render_user 接线）
    import inspect

    import noval_workflow.chapter_plan_edit_subgraph as cpe_mod

    src = inspect.getsource(cpe_mod)
    bs_count = src.count("build_system(")
    ru_count = src.count("render_user(")
    checks.append(
        (
            "G-cp_edit 三处 build_system 接线",
            bs_count >= 3,
            f"build_system 调用 {bs_count} 处" if bs_count >= 3 else f"仅 {bs_count} 处（应≥3）",
        )
    )
    checks.append(
        (
            "G-cp_edit 三处 render_user 接线",
            ru_count >= 3,
            f"render_user 调用 {ru_count} 处" if ru_count >= 3 else f"仅 {ru_count} 处（应≥3）",
        )
    )

    return checks


def main() -> int:
    state = build_mock_state()
    old_system, old_user = assemble_old_path(state)
    req, msgs = assemble_new_path(state)

    # ── 打印旧路径 ──
    _divider("旧路径 system（build_foundation_context 全量塞 system）")
    print(old_system)
    print(f"\n[字符数: {len(old_system)}]")
    _divider("旧路径 user（core_theme_prompt）")
    print(old_user[:500] + ("..." if len(old_user) > 500 else ""))

    # ── 打印新路径三层 ──
    _divider("新路径 L1 system（身份 + 硬契约 + 任务契约 + 优先级约定）")
    print(req.system)
    print(f"\n[字符数: {len(req.system)}]")

    _divider("新路径 L2 context（参考资料，从 system 移出）")
    new_context = "\n\n".join(s.body for s in req.context if s.body)
    print(new_context)
    print(f"\n[字符数: {len(new_context)}]")

    _divider("新路径 L3 task（本次指令 + 自检 + 输出格式）")
    print(req.task)
    print(f"\n[字符数: {len(req.task)}]")

    # ── 检查 ──
    checks = run_checks(old_system, old_user, req, msgs)
    _divider("自动检查（core_theme 三层）")
    all_pass = True
    for name, ok, detail in checks:
        flag = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False
        print(f"{flag}  {name}  --  {detail}")

    # ── foundation prepare 批量检查 ──
    prepare_checks = run_prepare_checks(state)
    _divider("foundation 7 prepare 批量检查")
    for name, ok, detail in prepare_checks:
        flag = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False
        print(f"{flag}  {name}  --  {detail}")

    # ── generate / 自审拼装 + 独立 LLM 点硬契约（步骤 09）──
    gen_checks = run_generate_self_review_checks(state)
    _divider("generate / 自审拼装 + 独立 LLM 点硬契约")
    for name, ok, detail in gen_checks:
        flag = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False
        print(f"{flag}  {name}  --  {detail}")

    _divider("结论")
    if all_pass:
        print(
            "✅ 全部检查通过：core_theme 三层 + foundation/chapter/snapshot prepare "
            "+ generate/自审拼装 + 独立 LLM 点硬契约，重构符合预期。"
        )
        return 0
    print("❌ 有检查未通过，请看上方 FAIL 项。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
