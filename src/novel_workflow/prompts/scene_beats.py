"""章级 scene beats 提示词与组装函数。

Scene beats 是章前节拍表（可跳步骤），把章纲的 4 字段（目标/阻碍/结果/代价）细化成
3–7 个结构化 beat，并把「打脸四拍 / 章尾钩 / 三段式爽感闭环」这些散落在 chapter_prompt
里的 doctrine 上升为 beat 上的 device_tags 硬约束枚举，让 LLM 无法绕开。

与 arc_outline（批次弧线）的职责边界：
- arc_outline 说"这批 5 章要走完 A→B→C 弧线"（章间层，每批一次）
- scene_beats 说"本章内部怎么用 5 个 beat 演出 A→A.5 这一段"（章内层，每章一次）

落地位置：scene_beats_step → prepare_chapter；save_chapter 之后由 chapter loop 清零，
防止下一章跳过 gate 时误用上一章的 beats（详见 state.py::beats_chapter_index 注释）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from noval_workflow.prompts.base import _extract_arc_chapter_block

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


# ── device_tag 枚举与文字说明（LLM prompt 里引用；save/review 校验也读它）─────────

# 「打脸四拍」的四个 tag——出现任一即视为打脸桥段，硬约束「四拍必须齐全」。
SLAP_TAGS = ("slap_taunt", "slap_silence", "slap_crush", "slap_witness")

# 「三段式爽感闭环」的三个 tag——单个爽点从压抑→蓄势→释放。
CATHARSIS_TAGS = ("setup", "buildup", "release")

# 钩子：开篇钩仅在章号 1 的首 beat 才合规；章尾钩必须挂在末 beat。
HOOK_TAGS = ("hook_opening", "hook_chapter_end")

# 伏笔：埋点 / 回收。
FORESHADOW_TAGS = ("foreshadow_plant", "foreshadow_recover")

# 缓冲：日常场景，防紧绷疲劳。
BUFFER_TAGS = ("buffer",)

# 全部合法 device_tag 集合——save/review 拿它做枚举校验。
ALL_DEVICE_TAGS = frozenset(SLAP_TAGS + CATHARSIS_TAGS + HOOK_TAGS + FORESHADOW_TAGS + BUFFER_TAGS)


# ── 生成提示词 ────────────────────────────────────────────────────────────────

SCENE_BEATS_PROMPT = """请为本章设计 scene beats——本章正文的场景节拍表，作为下一步正文创作的首要依据。

【本章定位】第 {chapter_num} 章《{title}》{batch_pos_desc}
【本章目标字数】{chapter_word_count}{arc_section}{chapter_context_section}

---

## 任务

输出 **3–7 个 beat** 组成的 JSON 数组：
- 短平快章（日常/过场/铺垫）3–4 个 beat
- 重章（打脸/爆点/身份揭晓/大战）5–7 个 beat

每个 beat 都是一个独立场景/节拍，逐 beat 展开正文，beat 之间用空行分场。

## 单个 beat 的字段（严格 JSON，缺一不可）

```json
{{
  "id": 1,
  "scene": "时/地/主要出场人物（≤20字）",
  "goal": "本 beat 主角要做什么（≤30字）",
  "obstacle": "阻碍/冲突（≤30字）",
  "outcome": "结果：成/败/悬置——必须带具体状态变化，禁止「聊完就散」（≤30字）",
  "cost": "付出的代价，防原地踏步——即使成功也要有代价（≤30字）",
  "emotion_arc": "情绪走向，如 屈辱→蓄力 / 麻木→爆发（≤20字）",
  "device_tags": ["setup"],
  "target_words": 800
}}
```

## device_tags 枚举（每 beat 至少 1 个，只能从下表选）

### 三段式爽感闭环（单个爽点桥段的三段结构）
- `setup`：压抑铺陈——把不公/嘲讽/危机写具体，越具体后面越爽
- `buildup`：蓄势——主角隐忍/布局/觉醒，张力积累
- `release`：释放——爽感外显，打脸/翻盘/碾压

### 打脸四拍（打脸桥段必用，缺一不可）
- `slap_taunt`：嘲讽——反派/众人看不起主角，越嚣张越好
- `slap_silence`：沉默——主角不辩解，淡淡出手（蓄势张力）
- `slap_crush`：碾压——实力/真相/反转一击致命
- `slap_witness`：围观——旁观者的震惊反应（最容易漏的一拍，但最爽）

### 钩子
- `hook_opening`：开篇钩——仅在**第 1 章的首 beat** 才能使用（3 句内立危机/反差）
- `hook_chapter_end`：章尾钩——**只能挂在最后一个 beat 上**，在情绪/动作最高点前一秒断章

### 伏笔
- `foreshadow_plant`：埋点——本 beat 首次埋下的伏笔线索
- `foreshadow_recover`：回收——兑现前文埋下的伏笔

### 节奏
- `buffer`：缓冲/日常——紧张段之间的舒缓，防读者疲劳

## 硬约束（必须满足，否则不合格重来）

1. **打脸四拍完整性**：只要出现任一 `slap_*` 标签，四拍必须**完整齐全** —— 缺任何一拍都不合格；不想做完整四拍就退化用 `release`（普通爽点释放）
2. **章尾钩位置**：`hook_chapter_end` **只能挂在最后一个 beat 上**，不能在中间出现
3. **开篇钩使用**：`hook_opening` **只在第 1 章的第 1 个 beat** 才合规；非第 1 章禁止使用
4. **有进有退**：每个 beat 的 outcome 必须带具体状态变化（人物位置/关系/信息/资源/伤势/情绪），禁止连续 3 个 beat 都是"悬置"或"聊完就散"
5. **字数分配**：所有 beat 的 target_words 累加应贴近【本章目标字数】（±20% 以内）
6. **弧线大纲对齐**：整章 beats 必须落实【本章弧线大纲锚点】的核心事件、人物行动、情节转折、伏笔线索，不抢写后续章节内容

## 输出格式（严格 JSON 数组，无 markdown 围栏）

直接输出如下结构的 JSON 数组，不要包裹在 ```json 里，不要有解释文字：

```
[
  {{"id": 1, "scene": "...", "goal": "...", "obstacle": "...", "outcome": "...", "cost": "...", "emotion_arc": "...", "device_tags": ["setup"], "target_words": 600}},
  {{"id": 2, ...}}
]
```

请直接输出 JSON 数组。"""


# ── 审核提示词 ────────────────────────────────────────────────────────────────

SCENE_BEATS_REVIEW_PROMPT = """请审核以下 scene beats 草稿，逐条检查是否符合硬性规则；无问题则回复「无问题」，有问题则列出具体条目。

【草稿】
{draft}

---

## 逐项检查（发现任何一项不合格都要指出，并给出改法）

1. **JSON 合法性**：能否被解析为顶层 list、每个元素都是 dict？字段是否齐全（id / scene / goal / obstacle / outcome / cost / emotion_arc / device_tags / target_words）？

2. **beat 数量**：3–7 个之间？短平快场景 3–4、重章 5–7 是否合理？

3. **device_tags 枚举合法性**：所有 tag 是否都在下列枚举内？——
   `setup` / `buildup` / `release` / `slap_taunt` / `slap_silence` / `slap_crush` / `slap_witness` /
   `hook_opening` / `hook_chapter_end` / `foreshadow_plant` / `foreshadow_recover` / `buffer`
   有任何非法值必须指出。

4. **打脸四拍完整性（硬约束）**：只要草稿里出现任一 `slap_*` tag，检查四个 `slap_taunt` / `slap_silence` / `slap_crush` / `slap_witness` 是否**四拍齐全**？缺任何一拍即视为不合格，必须补齐或整体退化为 `release`。

5. **章尾钩位置**：`hook_chapter_end` 是否**只在最后一个 beat** 上出现？出现在中间 beat 上不合格。

6. **开篇钩使用**：`hook_opening` 是否只在第 1 章的第 1 个 beat 上出现？非第 1 章使用不合格。

7. **有进有退（防止原地踏步）**：每个 beat 的 outcome 是否带具体变化？是否有连续 3 个 beat outcome 都是"悬置"或含糊描述？

8. **字数累加**：所有 target_words 累加是否贴近本章目标字数（±20%）？

9. **字段字数限制**：scene ≤20、goal/obstacle/outcome/cost ≤30、emotion_arc ≤20 字，超限指出。

---

严格判定，缺一即为不合格。若全部通过，直接回复「无问题」；否则逐条列出问题并给改法。"""


# ── 组装函数 ──────────────────────────────────────────────────────────────────

def scene_beats_prompt(state: "NovelState", chapter_context: str = "") -> str:
    """组装本章 scene beats 生成提示词。

    Args:
        state: NovelState 或 SceneBeatsSubState，需要含 chapter loop 上下文字段
            （total_chapters_written / current_batch_titles / current_chapter_index /
            current_arc_outline / chapter_word_count）。
        chapter_context: 由 build_chapter_context(state) 产出，含近期章节完整/概要。
    """
    chapter_num = state.total_chapters_written + 1
    title = state.current_batch_titles[state.current_chapter_index] if state.current_batch_titles else ""
    batch_pos = state.current_chapter_index + 1
    batch_total = len(state.current_batch_titles)
    batch_pos_desc = f"，本批第 {batch_pos}/{batch_total} 章。" if batch_total else "。"

    # 从本批弧线大纲抽本章专属那段（复用 base.py 已有工具函数）
    arc_section = ""
    if state.current_arc_outline and batch_pos:
        block = _extract_arc_chapter_block(state.current_arc_outline, batch_pos)
        if block:
            arc_section = f"\n【本章弧线大纲锚点】\n{block}"
        else:
            arc_section = "\n【本章弧线大纲锚点】见系统提示【本批章节弧线大纲】，请定位到本章对应段落。"

    chapter_context_section = ""
    if chapter_context:
        chapter_context_section = f"\n【前文章节参考】\n{chapter_context}"

    return SCENE_BEATS_PROMPT.format(
        chapter_num=chapter_num,
        title=title,
        batch_pos_desc=batch_pos_desc,
        chapter_word_count=state.chapter_word_count or "（未设定，按 2000-3000 规划）",
        arc_section=arc_section,
        chapter_context_section=chapter_context_section,
    )


# ── 结构化 beats → markdown 表（供 chapter_prompt 注入下游正文创作使用）──────────

def format_beats_for_chapter_prompt(beats: list[dict]) -> str:
    """把已定稿的 beats JSON 渲染成 markdown 列表，注入 chapter_prompt 里作为「首要依据」。

    输出示例：
        - Beat 1【scene】客栈门口，主角与李三初见
          目标：拿到王家书信 ｜ 阻碍：李三索要银两 ｜ 结果：给了 5 两银子拿到信
          代价：暴露身家 ｜ 情绪：戒备→释然 ｜ 目标字数：500
          device_tags: setup, foreshadow_plant

    LLM 拿到这份「结构化到 beat 的清单」比拿到一段章纲文字更难绕开。
    """
    if not beats:
        return ""
    lines: list[str] = []
    for beat in beats:
        bid = beat.get("id", "?")
        scene = beat.get("scene", "")
        goal = beat.get("goal", "")
        obstacle = beat.get("obstacle", "")
        outcome = beat.get("outcome", "")
        cost = beat.get("cost", "")
        emotion = beat.get("emotion_arc", "")
        tags = beat.get("device_tags", []) or []
        words = beat.get("target_words", "")
        tags_str = ", ".join(tags) if tags else "-"
        lines.append(
            f"- **Beat {bid}【{scene}】**\n"
            f"  - 目标：{goal} ｜ 阻碍：{obstacle} ｜ 结果：{outcome}\n"
            f"  - 代价：{cost} ｜ 情绪：{emotion} ｜ 目标字数：{words}\n"
            f"  - device_tags：{tags_str}"
        )
    return "\n".join(lines)


# ── 结构化校验（save_fn 落地后调，也可供 review 阶段程序化辅助）──────────────────

def validate_beats(beats: list[dict]) -> list[str]:
    """程序化检查 beats 是否符合硬约束，返回问题列表（空 = 全部合格）。

    与 LLM 自审配合：LLM 自审偶尔漏检结构性问题，这里做一层确定性兜底，避免非法 beats
    直接注入下游 chapter_prompt。当前只做「fail-loud」检查——把问题写日志，不阻断流程；
    是否阻断流程留给上层决定（若需硬阻断，save_fn 可 raise）。
    """
    problems: list[str] = []
    if not beats or not isinstance(beats, list):
        return ["beats 不是非空 list"]

    slap_seen = {tag: False for tag in SLAP_TAGS}
    last_index = len(beats) - 1

    for idx, beat in enumerate(beats):
        if not isinstance(beat, dict):
            problems.append(f"beat[{idx}] 不是 dict")
            continue
        tags = beat.get("device_tags", []) or []
        if not tags:
            problems.append(f"beat[{idx}] device_tags 为空")
        for tag in tags:
            if tag not in ALL_DEVICE_TAGS:
                problems.append(f"beat[{idx}] device_tag {tag!r} 不在枚举内")
            if tag in SLAP_TAGS:
                slap_seen[tag] = True
            if tag == "hook_chapter_end" and idx != last_index:
                problems.append(f"beat[{idx}] hook_chapter_end 未挂在末 beat（位置 {idx}/{last_index}）")
            if tag == "hook_opening" and idx != 0:
                problems.append(f"beat[{idx}] hook_opening 未挂在首 beat（位置 {idx}）")

    # 打脸四拍完整性硬约束：任一 slap_* 出现即要求四拍齐全
    if any(slap_seen.values()) and not all(slap_seen.values()):
        missing = [tag for tag, seen in slap_seen.items() if not seen]
        problems.append(f"打脸四拍不齐全，缺 {missing}")

    return problems


__all__ = [
    "SCENE_BEATS_PROMPT",
    "SCENE_BEATS_REVIEW_PROMPT",
    "ALL_DEVICE_TAGS",
    "SLAP_TAGS",
    "CATHARSIS_TAGS",
    "HOOK_TAGS",
    "FORESHADOW_TAGS",
    "BUFFER_TAGS",
    "scene_beats_prompt",
    "format_beats_for_chapter_prompt",
    "validate_beats",
]
