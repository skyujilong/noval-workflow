"""自定义 HTTP 路由：挂载 output 目录为静态文件服务 + 按小说的提示词覆盖读写接口。

通过 langgraph.json 的 http.app 配置加载，与平台 API 同端口（默认 8123）合并、
无前缀。前端经 <API_URL>/output/<小说名>/chapters/*.txt 读取章节正文；经
<API_URL>/prompt-overrides 读写该小说的提示词覆盖（覆盖题材风味字段）。

目录解析相对于 langgraph dev 的启动 cwd（项目根），默认 ./output；
可用 NOVEL_OUTPUT_DIR 环境变量覆盖（与 noval_workflow.context.get_output_dir 一致）。

注意：langgraph_api 运行时只安装了 starlette（无 fastapi），故此处用 Starlette。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import fields

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

# output 根目录：与 context.get_output_dir 保持同一来源
_output_dir = os.environ.get("NOVEL_OUTPUT_DIR", "./output")

# 挂载前确保目录存在：StaticFiles 构造时会校验 directory，缺失会抛 RuntimeError，
# 导致整个 langgraph dev 启动失败。./output 是工作流输出根目录，首启时尚未被创建，
# 这里无条件建空目录（exist_ok=True 幂等），不影响后续 save_chapter 等正常写入。
os.makedirs(_output_dir, exist_ok=True)


# ── 提示词覆盖接口 ───────────────────────────────────────────────────────────────
# 覆盖项粒度为 GenreFlavor 字段；存储不入 langgraph state，放在每本小说输出目录下的
# prompt_overrides.json（key = 安全小说名，与 config.json 同目录），每次节点运行新鲜读取。

async def get_prompt_overrides(request: Request) -> JSONResponse:
    """返回某小说的题材默认值（供前端预填）与已存覆盖项。

    query: novel=<原始小说名>, genre=<题材>
    resp:  {"defaults": {字段: 题材默认值...}, "overrides": {已存覆盖...}}
    """
    # 惰性 import：避免 http_app 模块加载期与图模块的导入顺序耦合
    from noval_workflow.prompts import GenreFlavor, get_prompt_pack, load_overrides

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    # 不传 novel_name 取得纯题材基础包，导出全字段默认值（前端无需硬编码字段集）
    pack = get_prompt_pack(genre)
    # 只导出 JSON 可序列化的标量字段(str/int/float/bool/None);
    # chapter_plan_prompt_builder 是 Callable 不能进 JSON,前端也无法覆盖它,直接排除。
    defaults = {
        f.name: getattr(pack.flavor, f.name)
        for f in fields(GenreFlavor)
        if isinstance(getattr(pack.flavor, f.name), (str, int, float, bool, type(None)))
    }
    # load_overrides 读盘是同步阻塞调用，放到线程里执行，避免阻塞 ASGI 事件循环
    overrides = await asyncio.to_thread(load_overrides, novel) if novel else {}
    return JSONResponse({"defaults": defaults, "overrides": overrides})


async def put_prompt_overrides(request: Request) -> JSONResponse:
    """保存某小说的提示词覆盖。

    query: novel=<原始小说名>
    body:  {"overrides": {字段: 文本...}}（仅含与默认不同的字段；后端再做安全过滤）
    """
    from noval_workflow.prompts import save_overrides

    novel = request.query_params.get("novel", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    overrides = body.get("overrides", {}) if isinstance(body, dict) else {}
    if not isinstance(overrides, dict):
        overrides = {}
    # save_overrides 做 mkdir + write_text，同步阻塞，放到线程里执行避免阻塞事件循环
    saved = await asyncio.to_thread(save_overrides, novel, overrides)
    return JSONResponse({"ok": True, "overrides": saved})


async def get_all_evolved_directives(request: Request) -> JSONResponse:
    """并排返回该小说三桶 evolved_directives 当前生效值——供「预览总体」抽屉使用。

    query: novel, genre。
    resp: {chapter: str, arc_outline: str, scene_beats: str, cross_bucket_overlaps: [...]}
    cross_bucket_overlaps:同一条(按行 hash)在多个桶都出现的整改,供 UI 高亮"跨环节重复"。
    """
    from noval_workflow.prompts import get_evolved_directives, get_prompt_pack

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    flavor = await asyncio.to_thread(lambda: get_prompt_pack(genre, novel).flavor)
    buckets = {
        "chapter": get_evolved_directives(flavor, "chapter"),
        "arc_outline": get_evolved_directives(flavor, "arc_outline"),
        "scene_beats": get_evolved_directives(flavor, "scene_beats"),
    }
    # 跨桶重复检测:按行(strip)聚合,同一行在多个桶出现则记为一条 overlap 项。
    line_to_buckets: dict[str, list[str]] = {}
    for bucket, text in buckets.items():
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            line_to_buckets.setdefault(line, []).append(bucket)
    overlaps = [
        {"text": line, "buckets": bkts}
        for line, bkts in line_to_buckets.items()
        if len(bkts) >= 2
    ]
    return JSONResponse({**buckets, "cross_bucket_overlaps": overlaps})


# ── 提示词自进化接口（按小说：提炼 / 应用 / 还原） ───────────────────────────────
# 把人工打回的修改要求提炼成整改，经确认写进该小说 prompt_overrides.json 的
# evolved_directives（下一次 prepare_chapter 新鲜读取即生效）；台账与可复用整改库落在
# 中央 SQLite（noval_workflow.prompts.evolution_store），图节点不碰。


def _current_prompt(genre: str, novel: str):
    """读取某小说当前生效(已合并覆盖)的相关提示词字段,供提炼去重/冲突判断。

    三桶隔离:分别把 chapter/arc_outline/scene_beats 三桶的 evolved_directives 传给 LLM,
    让它能全局去重(避免同一条规则在三个桶里重复出现)。distill 内部会按 review_type 把
    产出的 field 归一到当前环节对应桶。
    """
    from noval_workflow.prompts import get_prompt_pack
    from noval_workflow.prompts.evolution import CurrentPrompt

    flavor = get_prompt_pack(genre, novel).flavor
    return CurrentPrompt(
        chapter_style_rules=flavor.chapter_style_rules,
        chapter_review_checklist=flavor.chapter_review_checklist,
        evolved_directives_chapter=flavor.evolved_directives_chapter,
        evolved_directives_arc_outline=flavor.evolved_directives_arc_outline,
        evolved_directives_scene_beats=flavor.evolved_directives_scene_beats,
    )


def _event_to_json(ev) -> dict:
    """序列化进化事件给前端（省略体量较大、仅服务端还原用的 prompt_before）。"""
    return {
        "id": ev.id,
        "created_at": ev.created_at,
        "novel_name": ev.novel_name,
        "genre": ev.genre,
        "trigger": ev.trigger.value,
        "review_type": ev.review_type,
        "chapter_index": ev.chapter_index,
        "source_feedback": ev.source_feedback,
        "rejected_excerpt": ev.rejected_excerpt,
        "proposals": [
            {
                "field": p.field,
                "op": p.op.value,
                "text": p.text,
                "rationale": p.rationale,
                "conflicts_with": p.conflicts_with,
                "applies_to": list(p.applies_to),
            }
            for p in ev.proposals
        ],
        "status": ev.status.value,
        "applied": ev.applied,
        "applied_at": ev.applied_at,
        "reverted_at": ev.reverted_at,
    }


def _directive_to_json(d) -> dict:
    return {
        "id": d.id,
        "created_at": d.created_at,
        "genre": d.genre,
        "title": d.title,
        "text": d.text,
        "tags": list(d.tags),
        "source_novel": d.source_novel,
        "usage_count": d.usage_count,
    }


def _merge_field(base: str, text: str, op: str) -> str:
    """把一条整改文本按 append/replace 合到字段现值上。"""
    text = text.strip()
    if op == "replace" or not base.strip():
        return text
    return f"{base.rstrip()}\n{text}"


async def get_prompt_evolution(request: Request) -> JSONResponse:
    """列出某小说的进化事件台账（最新在前）。query: novel=<原始小说名>。"""
    from noval_workflow.prompts.evolution_store import get_events

    novel = request.query_params.get("novel", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    events = await asyncio.to_thread(get_events, novel)
    return JSONResponse({"events": [_event_to_json(e) for e in events]})


async def post_prompt_evolution_distill(request: Request) -> JSONResponse:
    """提炼一条人工修改意见为整改提案，落一条 proposed 事件并返回。

    query: novel, genre；body: {feedback, review_type?, draft_excerpt?, chapter_index?}
    """
    from noval_workflow.prompts.evolution import distill
    from noval_workflow.prompts.evolution_store import (
        EventTrigger,
        EvolutionEvent,
        EvolutionEventNotFound,
        add_event,
        update_event,
    )

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    body = await _json_body(request)
    feedback = str(body.get("feedback", "")).strip()
    if not feedback:
        return JSONResponse({"error": "missing feedback"}, status_code=400)
    review_type = str(body.get("review_type", "chapter"))
    draft_excerpt = str(body.get("draft_excerpt", ""))
    chapter_index = body.get("chapter_index")
    event_id = str(body.get("event_id", "")).strip()

    current = await asyncio.to_thread(_current_prompt, genre, novel)
    result = await asyncio.to_thread(distill, feedback, review_type, current, draft_excerpt)
    if event_id:
        # 就地提炼：把提案更新进已有事件（通常是打回自动落库的 REJECT 记录），不新建。
        try:
            saved = await asyncio.to_thread(update_event, event_id, proposals=result.proposals)
        except EvolutionEventNotFound:
            return JSONResponse({"error": "event not found"}, status_code=404)
    else:
        event = EvolutionEvent(
            novel_name=novel,
            genre=genre,
            trigger=EventTrigger.MANUAL,
            review_type=review_type,
            chapter_index=chapter_index if isinstance(chapter_index, int) else None,
            source_feedback=feedback,
            rejected_excerpt=draft_excerpt,
            proposals=result.proposals,
        )
        saved = await asyncio.to_thread(add_event, event)
    return JSONResponse({"event": _event_to_json(saved), "summary": result.summary})


async def post_prompt_evolution_reject(request: Request) -> JSONResponse:
    """打回自动落库：把一次人工打回的修改意见记一条 REJECT 事件（proposed，待提炼）。

    query: novel, genre；body: {review_type, feedback, chapter_index?}。
    供前端在 chapter/arc_outline 打回时自动调用；空 feedback（=通过）直接跳过。
    """
    from noval_workflow.prompts.evolution_store import (
        EventTrigger,
        EvolutionEvent,
        add_event,
    )

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    body = await _json_body(request)
    feedback = str(body.get("feedback", "")).strip()
    if not feedback:
        return JSONResponse({"ok": True, "skipped": True})
    review_type = str(body.get("review_type", "chapter"))
    chapter_index = body.get("chapter_index")
    event = EvolutionEvent(
        novel_name=novel,
        genre=genre,
        trigger=EventTrigger.REJECT,
        review_type=review_type,
        chapter_index=chapter_index if isinstance(chapter_index, int) else None,
        source_feedback=feedback,
    )
    saved = await asyncio.to_thread(add_event, event)
    return JSONResponse({"ok": True, "event": _event_to_json(saved)})


def _apply_selected(novel: str, genre: str, selected: list[dict]) -> tuple[dict, dict, dict]:
    """把选中的整改合并进该小说覆盖并落盘。返回 (落盘后 overrides, applied, 应用前快照)。

    支持「分发到多桶」:每项 selected 除了 field 主字段,还可带 also_apply_to=[<桶字段名>...],
    合并时对每个目标字段独立做 append/replace,让一条整改一次写入多桶。
    """
    from noval_workflow.prompts import (
        EVOLVED_DIRECTIVES_FIELDS,
        GenreFlavor,
        get_prompt_pack,
        load_overrides,
        save_overrides,
    )

    allowed = {f.name for f in fields(GenreFlavor)}
    prompt_before = load_overrides(novel)
    flavor = get_prompt_pack(genre, novel).flavor
    merged = dict(prompt_before)
    applied: dict[str, str] = {}
    for item in selected:
        field_name = str(item.get("field", "evolved_directives_chapter"))
        text = str(item.get("text", "")).strip()
        if field_name not in allowed or not text:
            continue
        op = str(item.get("op", "append"))
        # 主字段 + 分发目标一次性合并;分发目标限定在 evolved_directives_* 三桶(避免误分发到风格/审核清单)。
        raw_also = item.get("also_apply_to", [])
        also = [f for f in raw_also if isinstance(f, str) and f in EVOLVED_DIRECTIVES_FIELDS]
        targets = [field_name] + [f for f in also if f != field_name]
        for target in targets:
            base = merged.get(target) or getattr(flavor, target, "")
            merged[target] = _merge_field(base, text, op)
            applied[target] = merged[target]
    saved = save_overrides(novel, merged)
    return saved, applied, prompt_before


async def post_prompt_evolution_apply(request: Request) -> JSONResponse:
    """应用某事件里选中的整改到该小说覆盖，标记 applied 并记录应用前快照。

    query: novel, genre；body: {event_id, selected:[{field,text,op}]}
    """
    from noval_workflow.prompts.evolution_store import (
        EventStatus,
        _now,
        update_event,
    )

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    body = await _json_body(request)
    event_id = str(body.get("event_id", ""))
    selected = body.get("selected", [])
    if not event_id or not isinstance(selected, list) or not selected:
        return JSONResponse({"error": "missing event_id or selected"}, status_code=400)

    saved, applied, prompt_before = await asyncio.to_thread(
        _apply_selected, novel, genre, selected
    )
    if not applied:
        return JSONResponse({"error": "no valid selected fields"}, status_code=400)
    event = await asyncio.to_thread(
        update_event,
        event_id,
        status=EventStatus.APPLIED,
        applied=applied,
        prompt_before=prompt_before,
        applied_at=_now(),
    )
    return JSONResponse({"ok": True, "overrides": saved, "event": _event_to_json(event)})


async def post_prompt_evolution_restore(request: Request) -> JSONResponse:
    """把某已应用事件还原到应用前快照。query: novel；body: {event_id}。"""
    from noval_workflow.prompts import save_overrides
    from noval_workflow.prompts.evolution_store import (
        EventStatus,
        EvolutionEventNotFound,
        _now,
        get_event,
        update_event,
    )

    novel = request.query_params.get("novel", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    body = await _json_body(request)
    event_id = str(body.get("event_id", ""))
    if not event_id:
        return JSONResponse({"error": "missing event_id"}, status_code=400)
    try:
        event = await asyncio.to_thread(get_event, event_id)
    except EvolutionEventNotFound:
        return JSONResponse({"error": "event not found"}, status_code=404)
    saved = await asyncio.to_thread(save_overrides, novel, event.prompt_before)
    await asyncio.to_thread(
        update_event, event_id, status=EventStatus.REVERTED, reverted_at=_now()
    )
    return JSONResponse({"ok": True, "overrides": saved})


async def post_prompt_evolution_reconcile(request: Request) -> JSONResponse:
    """预览:把该小说某桶累积的 evolved_directives 整理消解成去重、无矛盾的自洽全集(不落盘)。

    query: novel, genre, review_type(可选,默认 chapter);body: {}。
    返回 {before, after, summary, resolved, field},field 告诉前端整理的是哪一桶。
    """
    from noval_workflow.prompts import evolved_field_for, get_evolved_directives, get_prompt_pack
    from noval_workflow.prompts.evolution import reconcile

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    review_type = request.query_params.get("review_type", "chapter")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    flavor = await asyncio.to_thread(lambda: get_prompt_pack(genre, novel).flavor)
    before = get_evolved_directives(flavor, review_type).strip()
    field = evolved_field_for(review_type)
    if not before:
        return JSONResponse(
            {"error": f"no {field} to reconcile"}, status_code=400
        )
    result = await asyncio.to_thread(reconcile, before, genre)
    return JSONResponse(
        {
            "before": before,
            "after": result.reconciled,
            "summary": result.summary,
            "resolved": list(result.resolved),
            "field": field,
            "review_type": review_type,
        }
    )


def _apply_reconciled(novel: str, genre: str, text: str, field: str) -> tuple[dict, dict]:
    """把整理后的 directives 全量 REPLACE 写进该小说覆盖某桶并落盘。返回 (overrides, 应用前快照)。"""
    from noval_workflow.prompts import EVOLVED_DIRECTIVES_FIELDS, load_overrides, save_overrides

    if field not in EVOLVED_DIRECTIVES_FIELDS:
        raise ValueError(f"reconcile 目标字段不合法: {field}")
    prompt_before = load_overrides(novel)
    merged = dict(prompt_before)
    merged[field] = text.strip()
    saved = save_overrides(novel, merged)
    return saved, prompt_before


async def post_prompt_evolution_reconcile_apply(request: Request) -> JSONResponse:
    """把整理后的 directives 全量 REPLACE 写进对应桶,记一条 reconcile 事件(含应用前快照,可还原)。

    query: novel, genre;body: {text, before?, summary?, review_type?, field?}。
    field 优先,缺省用 review_type 映射;两者都缺按 chapter 桶处理。
    """
    from noval_workflow.prompts import evolved_field_for
    from noval_workflow.prompts.evolution_store import (
        EventStatus,
        EventTrigger,
        EvolutionEvent,
        Proposal,
        ProposalOp,
        _now,
        add_event,
    )

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    body = await _json_body(request)
    text = str(body.get("text", "")).strip()
    if not text:
        return JSONResponse({"error": "missing text"}, status_code=400)
    before = str(body.get("before", ""))
    summary = str(body.get("summary", "")).strip()
    review_type = str(body.get("review_type", "chapter"))
    field = str(body.get("field", "")) or evolved_field_for(review_type)

    saved, prompt_before = await asyncio.to_thread(
        _apply_reconciled, novel, genre, text, field
    )
    event = EvolutionEvent(
        novel_name=novel,
        genre=genre,
        trigger=EventTrigger.RECONCILE,
        review_type=review_type,
        source_feedback=summary or "整理消解累积整改要点",
        rejected_excerpt=before,
        proposals=(
            Proposal(
                field=field,
                text=text,
                op=ProposalOp.REPLACE,
                rationale="整理消解:去重 + 消解矛盾 + 后者优先",
            ),
        ),
        status=EventStatus.APPLIED,
        applied={field: saved.get(field, "")},
        prompt_before=prompt_before,
        applied_at=_now(),
    )
    saved_event = await asyncio.to_thread(add_event, event)
    return JSONResponse({"ok": True, "overrides": saved, "event": _event_to_json(saved_event)})


# ── 整改库接口（跨小说：精炼入库 / 查询 / 导入） ────────────────────────────────


async def post_prompt_library_refine(request: Request) -> JSONResponse:
    """把某小说某桶累积的 evolved_directives 精炼拆成候选原子条目(不落库,供前端勾选)。

    query: novel, genre, review_type(默认 chapter)。resp: {items:[{title,text,tags}]}
    """
    from noval_workflow.prompts import get_evolved_directives, get_prompt_pack
    from noval_workflow.prompts.evolution import refine_to_items

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    review_type = request.query_params.get("review_type", "chapter")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    flavor = await asyncio.to_thread(lambda: get_prompt_pack(genre, novel).flavor)
    directives = get_evolved_directives(flavor, review_type)
    items = await asyncio.to_thread(refine_to_items, directives, genre)
    return JSONResponse(
        {"items": [{"title": it.title, "text": it.text, "tags": list(it.tags)} for it in items]}
    )


async def post_prompt_library(request: Request) -> JSONResponse:
    """把选中的候选条目入中央整改库。query: genre；body: {items:[{title,text,tags}], source_novel?}"""
    from noval_workflow.prompts.evolution_store import DirectiveItem, add_directives

    genre = request.query_params.get("genre", "")
    body = await _json_body(request)
    raw_items = body.get("items", [])
    source_novel = str(body.get("source_novel", ""))
    if not isinstance(raw_items, list) or not raw_items:
        return JSONResponse({"error": "missing items"}, status_code=400)
    items = [
        DirectiveItem(
            genre=genre,
            title=str(it.get("title", "")).strip(),
            text=str(it.get("text", "")).strip(),
            tags=tuple(str(t) for t in it.get("tags", []) if isinstance(it.get("tags", []), list)),
            source_novel=source_novel,
        )
        for it in raw_items
        if isinstance(it, dict) and str(it.get("text", "")).strip()
    ]
    saved = await asyncio.to_thread(add_directives, items)
    return JSONResponse({"items": [_directive_to_json(d) for d in saved]})


async def get_prompt_library(request: Request) -> JSONResponse:
    """查询整改库。query: genre, q, all（all=1 放宽到全部题材）。resp: {items:[...]}"""
    from noval_workflow.prompts.evolution_store import query_directives

    genre = request.query_params.get("genre", "")
    q = request.query_params.get("q", "")
    show_all = request.query_params.get("all", "") in ("1", "true", "yes")
    items = await asyncio.to_thread(
        query_directives, None if show_all else (genre or None), q or None
    )
    return JSONResponse({"items": [_directive_to_json(d) for d in items]})


def _import_directives(
    novel: str, genre: str, item_ids: list[str], field: str
) -> tuple[dict, dict, int]:
    """取库条目、去重追加进该小说某桶 evolved_directives 并落盘。返回 (overrides, 应用前快照, 导入数)。"""
    from noval_workflow.prompts import (
        EVOLVED_DIRECTIVES_FIELDS,
        get_prompt_pack,
        load_overrides,
        save_overrides,
    )
    from noval_workflow.prompts.evolution_store import bump_usage, get_directives

    if field not in EVOLVED_DIRECTIVES_FIELDS:
        raise ValueError(f"import 目标字段不合法: {field}")
    directives = get_directives(item_ids)
    prompt_before = load_overrides(novel)
    flavor = get_prompt_pack(genre, novel).flavor
    current = prompt_before.get(field) or getattr(flavor, field, "")
    merged = current
    added = 0
    for d in directives:
        if d.text.strip() and d.text.strip() not in merged:
            merged = _merge_field(merged, d.text, "append")
            added += 1
    if added == 0:
        return prompt_before, prompt_before, 0
    overrides = dict(prompt_before)
    overrides[field] = merged
    saved = save_overrides(novel, overrides)
    bump_usage([d.id for d in directives])
    return saved, prompt_before, added


async def post_prompt_library_import(request: Request) -> JSONResponse:
    """把选中的库条目导入某小说某桶 evolved_directives(去重追加),记一条 import 事件。

    query: novel, genre;body: {item_ids:[...], review_type?, field?}
    """
    from noval_workflow.prompts import evolved_field_for
    from noval_workflow.prompts.evolution_store import (
        EventStatus,
        EventTrigger,
        EvolutionEvent,
        _now,
        add_event,
    )

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    body = await _json_body(request)
    item_ids = body.get("item_ids", [])
    if not isinstance(item_ids, list) or not item_ids:
        return JSONResponse({"error": "missing item_ids"}, status_code=400)
    review_type = str(body.get("review_type", "chapter"))
    field = str(body.get("field", "")) or evolved_field_for(review_type)

    saved, prompt_before, added = await asyncio.to_thread(
        _import_directives, novel, genre, [str(i) for i in item_ids], field
    )
    if added == 0:
        return JSONResponse({"ok": True, "overrides": saved, "imported": 0})
    event = EvolutionEvent(
        novel_name=novel,
        genre=genre,
        trigger=EventTrigger.IMPORT,
        review_type=review_type,
        source_feedback=f"从整改库导入 {added} 条 → {field}",
        applied={field: saved.get(field, "")},
        prompt_before=prompt_before,
        status=EventStatus.APPLIED,
        applied_at=_now(),
    )
    await asyncio.to_thread(add_event, event)
    return JSONResponse({"ok": True, "overrides": saved, "imported": added})


async def _json_body(request: Request) -> dict:
    """安全解析 JSON body，非法/非对象一律回 {}。"""
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


# ── 小说列表摘要接口（轻量化轮询） ───────────────────────────────────────────────
# 平台 POST /threads/search 会为每个 thread 返回完整 values（整个 NovelState，含正文/大纲
# /人物档案等大字段）。前端列表 3s 轮询只需 novel_name / total_chapters_written / status，
# 全量拉取使单次 payload 达数百 KB。此接口在服务端自调用平台 search 后把 values 裁成白名单，
# 结构与 search 一致（仅 values 变小），前端可零成本映射，payload 降到几 KB。

# 列表/配置抽屉实际读到的 values 字段（均为 state.py 里的小标量），其余大字段一律不返回。
_SUMMARY_VALUE_FIELDS = ("novel_name", "genre", "total_chapters_written")

_lg_client = None  # 模块级懒缓存：langgraph 平台 SDK 客户端（自调用本机平台 API）


def _get_lg_client():
    global _lg_client
    if _lg_client is None:
        # 惰性 import：langgraph_sdk 是平台依赖，dev 运行时必装
        from langgraph_sdk import get_client

        # 自调用同进程的平台 API；端口与 dev-backend.sh 一致（.env.local 的 LANGGRAPH_PORT）
        port = os.environ.get("LANGGRAPH_PORT", "28123")
        _lg_client = get_client(url=f"http://127.0.0.1:{port}")
    return _lg_client


async def get_novels_summary(request: Request) -> JSONResponse:
    """小说（thread）列表摘要：与 /threads/search 同形状，但 values 仅含摘要白名单字段。

    query: limit=<最多返回数，默认 200>
    resp:  [{ thread_id, status, created_at, updated_at, metadata,
             values: {白名单字段}, pending_resume: bool }, ...]

    pending_resume 语义：thread 处于 status=interrupted，且平台去归一后的 interrupts dict
    为空（即：不是真正的 human-in-the-loop 中断，而是上一次 run 未正常收尾，checkpoint 里
    还有 pending task 但没有活跃 run 在推）。前端据此在列表卡片渲染「▶」按钮，一键继续。
    典型触发场景：langgraph dev 服务重启、后端进程被 kill、网络断开导致 run 挂起。
    """
    try:
        limit = int(request.query_params.get("limit", "200"))
    except ValueError:
        limit = 200

    try:
        threads = await _get_lg_client().threads.search(limit=limit)
    except Exception as e:  # 自调用失败时回清晰错误，前端 useThreads 会捕获展示
        return JSONResponse({"error": f"threads.search failed: {e}"}, status_code=502)

    out = []
    for t in threads:
        values = t.get("values") or {}
        # 只挑白名单标量；total_chapters_written 缺省安全取 0（全新未运行的 thread）
        summary = {k: values.get(k) for k in _SUMMARY_VALUE_FIELDS}
        summary["total_chapters_written"] = values.get("total_chapters_written", 0)
        # pending_resume：status=interrupted 但 interrupts dict 为空 → 无真中断，仅 pending 卡住。
        # interrupts 平台返回 dict（按 task_id 键控）；empty 检测涵盖 None / {} / []。
        interrupts = t.get("interrupts")
        has_real_interrupt = bool(interrupts) if interrupts is not None else False
        pending_resume = t.get("status") == "interrupted" and not has_real_interrupt
        out.append(
            {
                "thread_id": t["thread_id"],
                "status": t.get("status"),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
                "metadata": t.get("metadata") or {},
                "values": summary,
                "pending_resume": pending_resume,
            }
        )
    return JSONResponse(out)


# ── 应用组装 ─────────────────────────────────────────────────────────────────────
# 前端直连 langgraph dev（跨域），写接口（PUT）会触发预检，故挂 CORS 中间件放行。
routes = [
    Route("/prompt-overrides", get_prompt_overrides, methods=["GET"]),
    Route("/prompt-overrides", put_prompt_overrides, methods=["PUT"]),
    Route("/prompt-overrides/all-evolved", get_all_evolved_directives, methods=["GET"]),
    # 提示词自进化（按小说：提炼 / 应用 / 还原）
    Route("/prompt-evolution", get_prompt_evolution, methods=["GET"]),
    Route("/prompt-evolution/reject", post_prompt_evolution_reject, methods=["POST"]),
    Route("/prompt-evolution/distill", post_prompt_evolution_distill, methods=["POST"]),
    Route("/prompt-evolution/apply", post_prompt_evolution_apply, methods=["POST"]),
    Route("/prompt-evolution/restore", post_prompt_evolution_restore, methods=["POST"]),
    Route("/prompt-evolution/reconcile", post_prompt_evolution_reconcile, methods=["POST"]),
    Route(
        "/prompt-evolution/reconcile/apply",
        post_prompt_evolution_reconcile_apply,
        methods=["POST"],
    ),
    # 整改库（跨小说：精炼入库 / 查询 / 导入）
    Route("/prompt-library", get_prompt_library, methods=["GET"]),
    Route("/prompt-library", post_prompt_library, methods=["POST"]),
    Route("/prompt-library/refine", post_prompt_library_refine, methods=["POST"]),
    Route("/prompt-library/import", post_prompt_library_import, methods=["POST"]),
    # 小说列表轻量摘要（替代前端对 /threads/search 的全量轮询）
    Route("/novels/summary", get_novels_summary, methods=["GET"]),
    # 不挂 html 索引：仅按文件名访问，避免暴露所有小说的文件清单
    Mount("/output", StaticFiles(directory=_output_dir), name="output"),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(routes=routes, middleware=middleware)
