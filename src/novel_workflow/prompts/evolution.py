"""提示词自进化的两个 LLM 动作：提炼（distill）与精炼入库拆条（refine_to_items）。

- distill：把一条人工打回的「修改要求」提炼成简洁、去重、可执行的整改提案，主要追加到
  evolved_directives（也可补章节审核清单）。**冲突侦测**：与当前生效规则矛盾时，把整改
  措辞成显式覆盖（「将 X 改为 Y，覆盖原 X」）并回填 conflicts_with，让冲突可见、后者优先。
- refine_to_items：把某小说累积的 evolved_directives 拆成原子、自洽、去重的整改条目，
  供打题材标签入中央整改库、跨小说复用。

只做「反馈 → 结构化整改」的纯转换；落库/应用/导入由 evolution_store + http_app 负责。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from noval_workflow.llm import get_llm
from noval_workflow.prompts.evolution_store import Proposal, ProposalOp

# 整改提案允许落到的字段（其余一律归到 evolved_directives 累积字段）。
_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {"evolved_directives", "chapter_review_checklist", "chapter_style_rules"}
)


class EvolutionParseError(ValueError):
    """LLM 返回无法解析为预期 JSON 结构。"""


# ── 输入 / 输出模型 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CurrentPrompt:
    """提炼时提供给 LLM 的「当前生效提示词」快照，用于去重与冲突侦测。"""

    chapter_style_rules: str = ""
    chapter_review_checklist: str = ""
    evolved_directives: str = ""


@dataclass(frozen=True)
class DistillResult:
    """distill 的结构化结果。"""

    proposals: tuple[Proposal, ...]
    summary: str = ""


@dataclass(frozen=True)
class RefinedItem:
    """refine_to_items 拆出的单条可入库整改条目。"""

    title: str
    text: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconcileResult:
    """reconcile 的结构化结果：整理后的自洽全集 + 变更说明 + 逐条消解说明。"""

    reconciled: str
    summary: str = ""
    resolved: tuple[str, ...] = ()


# ── JSON 解析（容错） ────────────────────────────────────────────────────────


def _content_to_text(content: object) -> str:
    """把 LLM 返回内容归一为纯文本（兼容 str 与内容块列表）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts)
    return str(content)


def _extract_json(raw: str, kind: type) -> object:
    """从 LLM 文本里剥出 JSON（去 ```json 围栏），解析为 dict 或 list。

    kind 传 dict 或 list，指定期望的顶层类型；不匹配或解析失败抛 EvolutionParseError。
    """
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    open_ch = "[" if kind is list else "{"
    start = text.find(open_ch)
    if start == -1:
        raise EvolutionParseError(f"未找到 {open_ch} 开头的 JSON 片段：{raw[:200]}")
    # raw_decode 只解析从 start 起的第一个完整 JSON 值，容忍其后残留的说明文字。
    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise EvolutionParseError(f"JSON 解析失败：{exc}; 原文：{raw[:200]}") from exc
    if not isinstance(data, kind):
        raise EvolutionParseError(f"顶层不是 {kind.__name__}：{raw[:200]}")
    return data


def _coerce_field(name: object) -> str:
    """把 LLM 给的 field 归一到允许集合；未知/非法一律归到 evolved_directives。"""
    return name if isinstance(name, str) and name in _ALLOWED_FIELDS else "evolved_directives"


def _coerce_op(name: object) -> ProposalOp:
    if isinstance(name, str) and name.lower() == "replace":
        return ProposalOp.REPLACE
    return ProposalOp.APPEND


# ── distill：修改要求 → 整改提案 ─────────────────────────────────────────────

_DISTILL_SYSTEM = (
    "你是小说创作提示词的「进化工程师」。你的职责：把编辑对某一章的人工修改意见，"
    "提炼成可复用、可执行、简洁去重的写作整改规则，沉淀进后续所有章节的生成提示词。"
    "只产出规则本身，不复述意见、不解释过程。"
)


def _distill_prompt(
    feedback: str, review_type: str, current: CurrentPrompt, draft_excerpt: str
) -> str:
    excerpt = f"\n\n【被打回的正文片段（节选，供定位问题）】\n{draft_excerpt.strip()}" if draft_excerpt.strip() else ""
    return f"""【本次人工修改意见】（review_type={review_type}）
{feedback.strip()}
{excerpt}

【当前已生效的相关提示词规则（用于去重与冲突判断）】
- 章节文体风格(chapter_style_rules)：
{current.chapter_style_rules.strip() or "（空）"}
- 章节审核清单(chapter_review_checklist)：
{current.chapter_review_checklist.strip() or "（空）"}
- 历史整改要点(evolved_directives)：
{current.evolved_directives.strip() or "（空）"}

【任务】把上面的人工意见提炼为 1-4 条整改规则：
- 每条规则简洁、祈使句、可直接指导后续章节写作；与「当前已生效规则」重复的不要再产出。
- 目标字段 field 一般用 "evolved_directives"（累积历史整改要点）；若本质是审核清单项可用
  "chapter_review_checklist"。op 用 "append"（追加）。
- 冲突处理：若某条规则与「当前已生效规则」相矛盾（例如原来要求 A、现在要求非 A），
  必须把 text 写成显式覆盖措辞（「将 X 改为 Y，覆盖原关于 X 的要求」），并在 conflicts_with
  里写出被覆盖的原规则要点；不冲突则 conflicts_with 留空字符串。

【仅输出以下 JSON，不要任何多余文字】
{{"proposals":[{{"field":"evolved_directives","op":"append","text":"...","rationale":"...","conflicts_with":""}}],"summary":"一句话概述本次整改"}}"""


def distill(
    feedback: str,
    review_type: str,
    current: CurrentPrompt,
    draft_excerpt: str = "",
) -> DistillResult:
    """把人工修改意见提炼为结构化整改提案（含冲突侦测）。feedback 为空则返回空结果。"""
    if not feedback.strip():
        return DistillResult(proposals=(), summary="")
    llm = get_llm(temperature=0.4, label="evolve:distill", thinking="disabled")
    result = llm.invoke(
        [
            SystemMessage(content=_DISTILL_SYSTEM),
            HumanMessage(content=_distill_prompt(feedback, review_type, current, draft_excerpt)),
        ]
    )
    data = _extract_json(_content_to_text(result.content), dict)
    raw_proposals = data.get("proposals", []) if isinstance(data, dict) else []
    proposals = tuple(
        Proposal(
            field=_coerce_field(p.get("field")),
            text=str(p.get("text", "")).strip(),
            op=_coerce_op(p.get("op")),
            rationale=str(p.get("rationale", "")).strip(),
            conflicts_with=str(p.get("conflicts_with", "")).strip(),
        )
        for p in raw_proposals
        if isinstance(p, dict) and str(p.get("text", "")).strip()
    )
    summary = str(data.get("summary", "")).strip() if isinstance(data, dict) else ""
    return DistillResult(proposals=proposals, summary=summary)


# ── refine_to_items：累积整改 → 原子入库条目 ────────────────────────────────

_REFINE_SYSTEM = (
    "你是小说创作提示词的「整改库编辑」。你的职责：把一本小说累积的历史整改要点，"
    "拆分、去重、精炼成一条条独立自洽的通用整改条目，供同题材其他小说复用。"
)


def _refine_prompt(evolved_directives: str, genre: str) -> str:
    return f"""【题材】{genre or "通用"}

【某小说累积的历史整改要点（可能杂乱、重复、含具体人名/情节）】
{evolved_directives.strip()}

【任务】把上面内容拆成若干条**独立、自洽、去重、可复用**的整改条目：
- 每条只讲一个整改点，祈使句，去掉与本书强绑定的专有名词，使其对同题材通用；
- 合并语义重复项；剔除过于个别、无法复用的条目；
- 每条给一个不超过 12 字的短标题 title，正文 text，以及 1-3 个便于检索的标签 tags。

【仅输出以下 JSON 数组，不要任何多余文字】
[{{"title":"...","text":"...","tags":["...","..."]}}]"""


def refine_to_items(evolved_directives: str, genre: str) -> list[RefinedItem]:
    """把累积的 evolved_directives 拆成原子可入库条目。内容为空则返回 []。"""
    if not evolved_directives.strip():
        return []
    llm = get_llm(temperature=0.4, label="evolve:refine", thinking="disabled")
    result = llm.invoke(
        [
            SystemMessage(content=_REFINE_SYSTEM),
            HumanMessage(content=_refine_prompt(evolved_directives, genre)),
        ]
    )
    data = _extract_json(_content_to_text(result.content), list)
    items: list[RefinedItem] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", "")).strip()
        if not text:
            continue
        raw_tags = it.get("tags", [])
        tags = tuple(str(t).strip() for t in raw_tags if str(t).strip()) if isinstance(raw_tags, list) else ()
        items.append(
            RefinedItem(title=str(it.get("title", "")).strip(), text=text, tags=tags)
        )
    return items


# ── reconcile：累积整改 → 去重消解矛盾后的自洽全集 ──────────────────────────────

_RECONCILE_SYSTEM = (
    "你是小说创作提示词的「整改消解官」。你的职责：把一本小说历次累积、可能重复甚至"
    "互相矛盾的历史整改要点，重写成一份去重、消解矛盾、逻辑自洽的最终整改清单，"
    "供后续所有章节稳定执行。只做整理消解，不新增原文没有的要求。"
)


def _reconcile_prompt(evolved_directives: str, genre: str) -> str:
    return f"""【题材】{genre or "通用"}

【某小说累积的历史整改要点（按沉淀先后排列，可能重复、宽泛，甚至互相矛盾）】
{evolved_directives.strip()}

【任务】把上面内容重写成一份**去重、消解矛盾、逻辑自洽**的最终整改清单：
- 合并语义重复项，保留信息最全的表述；
- 若多条互相矛盾（如先要求 A、后要求非 A），**以更靠后（更新）的为准**，只保留最新意图，删除被推翻的旧项；
- 每条一行、祈使句、可直接指导后续章节写作；不加编号、不加解释；
- 只减不增：条数应比原文更少或持平，严禁引入原文没有的新要求。

【仅输出以下 JSON，不要任何多余文字】
{{"reconciled":"整理后的清单，每条一行","summary":"一句话概述本次整理（如：合并N条重复、消解M处矛盾）","resolved":["被消解的矛盾或合并项的简述","..."]}}"""


def reconcile(evolved_directives: str, genre: str) -> ReconcileResult:
    """把累积的 evolved_directives 整理成去重消解矛盾后的自洽全集。内容为空则返回空结果。"""
    if not evolved_directives.strip():
        return ReconcileResult(reconciled="", summary="")
    llm = get_llm(temperature=0.3, label="evolve:reconcile", thinking="disabled")
    result = llm.invoke(
        [
            SystemMessage(content=_RECONCILE_SYSTEM),
            HumanMessage(content=_reconcile_prompt(evolved_directives, genre)),
        ]
    )
    data = _extract_json(_content_to_text(result.content), dict)
    reconciled = str(data.get("reconciled", "")).strip() if isinstance(data, dict) else ""
    summary = str(data.get("summary", "")).strip() if isinstance(data, dict) else ""
    raw_resolved = data.get("resolved", []) if isinstance(data, dict) else []
    resolved = (
        tuple(str(r).strip() for r in raw_resolved if str(r).strip())
        if isinstance(raw_resolved, list)
        else ()
    )
    return ReconcileResult(reconciled=reconciled, summary=summary, resolved=resolved)
