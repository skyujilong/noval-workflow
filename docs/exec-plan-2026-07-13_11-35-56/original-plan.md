# 每章正文完成后自动发现新角色档案

## Context（为什么做这个）

**问题**：目前 `state.character_profiles`（人物档案）是 Phase 1 一次生成、Phase 2 冻结不动的自由格式 markdown。但小说章节写作过程里会不断出现**新登场角色**或**已有角色暴露出新信息**（新能力、新关系、新动机）。这些"发现"当前只存在于章节正文里，从未回流到 `state.character_profiles`，导致：

1. 下一章 `chapter_prompt` 的 `【人物档案】` 上下文永远是初版档案，AI 不知道本章新角色的存在。
2. 后续 `scene_beats` / `chapter_edit_subgraph` 的一致性做不出来（无处比对新角色）。
3. 用户看不到"角色档案是活的"，无法在书写过程中审阅并沉淀发现。

**目标**：每章正文写完后自动进入一个"发现"节点：LLM 读本章正文 + 已有 `character_profiles` → 产出**合流后的完整档案 markdown** → LLM 自审 → interrupt 交用户审核（可编辑/打回重跑/空回车通过）→ 覆盖写回 `state.character_profiles`，让新角色 / 新信息在下一章的 `build_foundation_context` 里可见。

**四个已确认的关键决策**（用户在 AskUserQuestion 里选定）：
1. **合流回 `character_profiles: str`**，不改字段类型、不新增结构化字段。
2. **完整 review_subgraph**（generate → llm_self_review → human_review），对齐 scene_beats。
3. **前端复用 `HumanReviewForm`**（review_type = `character_profiles_discover` → FormKind = `human_review`），不写专用组件；用户以文本反馈打回或空回车通过。
4. **每章都跑**：插在 `generate_summary` → `chapter_edit_subgraph` 之间，走 entry_gate 空回车即可整章跳过。

**核心设计取舍**：LLM **一次性全量输出**"合流后的完整档案 markdown"（save 端直接 `state.character_profiles = current_draft`）。理由：`str` 字段无结构 anchor，代码合流更脆；HumanReviewForm 直接展示完整档案便于比对；打回重跑时 LLM 重吐完整档案，用户看到什么就是最终写回什么，避免"审核 draft ≠ 落地内容"。

---

## 一、新建文件（3 个）

### 1. `src/novel_workflow/character_profiles_discover_subgraph.py`
**参照**：`src/novel_workflow/scene_beats_subgraph.py`

- 定义 `@dataclass class CharacterProfilesDiscoverSubState(EditStepSubState)`：**不需要额外字段**（`character_profiles: str` 已在 `EditStepSubState`（`edit_step_subgraph.py:79`）镜像，LangGraph 会按字段名自动桥接）。为保持与 `SceneBeatsSubState` 的对称形态、便于未来扩展，仍显式创建空子类。
- 模块级常量 `_ENTRY_HINT`，格式对齐 `scene_beats_subgraph.py:39`。
- 顶级导出对象 `character_profiles_discover_step = make_edit_step_subgraph(...)`。

`make_edit_step_subgraph` 参数：
```
entry_prompt        = "是否根据本章正文发现新角色 / 补充已知角色档案？" + _ENTRY_HINT
prepare_fn          = _prepare_character_profiles_discover
save_fn             = _save_character_profiles_discover
entry_gate_type     = InterruptType.CHARACTER_PROFILES_DISCOVER_ENTRY_GATE
direction_type      = InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT  # 必传参数，即便 ask_direction=False
enable_llm_review   = True
llm_review_max      = 2   # 宽松审核 + 每章一次，2 轮控 token
ask_direction       = False
enable_prune        = False
state_cls           = CharacterProfilesDiscoverSubState
```

### 2. `src/novel_workflow/nodes/character_profiles_discover.py`
**参照**：`src/novel_workflow/nodes/scene_beats.py`

- `def _prepare_character_profiles_discover(state) -> dict`
  返回 `{"system_context": build_foundation_context(state), "task_prompt": character_profiles_discover_prompt(state), "review_type": "character_profiles_discover"}`。
- `def _save_character_profiles_discover(state) -> dict`
  空 draft 兜底：`if not state.current_draft: _logger.warning(...); return {}`（不 clobber）；
  否则 `return {"character_profiles": state.current_draft}`——直接覆盖父图字段。

### 3. `src/novel_workflow/prompts/character_profiles_discover.py`
**参照**：`src/novel_workflow/prompts/scene_beats.py`（生成 + 审核 prompt 合并单文件）

导出常量与函数：
- `CHARACTER_PROFILES_DISCOVER_PROMPT: str` — 生成 prompt 模板，占位符 `{chapter_num}` / `{existing_profiles}` / `{chapter_draft}`。
- `CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT: str` — 审核 prompt 模板，占位符 `{draft}`。
- `def character_profiles_discover_prompt(state) -> str` — 组装函数：读 `state.current_draft`（本章正文，save_chapter 之后未被清空）、`state.character_profiles`（已有档案）、`state.total_chapters_written + 1`（本章号，1-based），返回 `.format()` 后的完整 prompt。

**生成 prompt 要点**（约束条目，不写全文）：
- 任务定位：本章正文已完成，识别新角色 / 补充已知角色新信息，输出**合流后的完整 markdown**（整块替换 `state.character_profiles`）。
- **保真硬约束**：必须保留【已有人物档案】所有主角 / 核心配角 / 反派条目原样，禁止裁剪、总结、重写；只在末尾追加新发现角色或在原有条目末尾追加"【第 N 章新增】…"补充段。
- 宽松形式：新次要角色允许只有 3-5 行简介，不要求力量体系归属 / 双层人设 / 成长天花板等初版 `CHARACTER_PROFILES_REVIEW_PROMPT` 的硬清单。
- 反幻觉：不得凭空虚构本章未提及的角色；不得改写已定角色的既定人设（性格、立场、能力上限），只能"追加"。
- 无新角色时允许原样吐回 `existing_profiles`（用于打回重跑或用户判断错时的兜底）。

**审核 prompt 要点**：
- 明确声明"**不检查**【卡司配额 / 双层人设 / 能力底牌契约 / 力量体系归属】等硬清单"（防串接 `CHARACTER_PROFILES_REVIEW_PROMPT`）。
- 只查三点：① 是否保留了原档案全部条目（防 LLM 压缩）；② 新增角色是否确实在本章正文中出现（防幻觉）；③ 新增段插入位置是否合理。
- 通过阈值放宽：满足三点即输出 pass 信号（`subgraph.py:PASS_SIGNALS` 之一）。

---

## 二、修改现有文件（7 处）

### `src/novel_workflow/state.py`
**无需修改**。`character_profiles: str` 字段类型不变；`current_draft / review_history / llm_review_count / approved` 均已在 `ReviewSubState`（`state.py:7-33`）里；不加"本章号锚定"字段（每章 discover 独立、覆盖写即幂等，不同于 scene_beats 的 `beats_chapter_index`）。

### `src/novel_workflow/graph.py`
- **第 65 行 imports** 后追加：`from noval_workflow.character_profiles_discover_subgraph import character_profiles_discover_step`
- **第 135 行 `builder.add_node("scene_beats_step", ...)` 附近**追加：`builder.add_node("character_profiles_discover_step", character_profiles_discover_step)`
- **第 265 行 `builder.add_edge("generate_summary", "chapter_edit_subgraph")`** 拆成两段：
  - `builder.add_edge("generate_summary", "character_profiles_discover_step")`
  - `builder.add_edge("character_profiles_discover_step", "chapter_edit_subgraph")`

章循环回跳（`route_chapter_or_continue`，`graph.py:268-272`）仍回到 `scene_beats_step`，下一章正常再次经过 discover 节点。

### `src/novel_workflow/interrupt_types.py`
- **第 70 行 `SCENE_BEATS_REVIEW` 之后**新增（分节注释对齐）：
  ```
  # 章级角色档案发现（每章正文完成后自动，可跳步骤）
  CHARACTER_PROFILES_DISCOVER_ENTRY_GATE  = "character_profiles_discover_entry_gate"
  CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT = "character_profiles_discover_direction_input"
  CHARACTER_PROFILES_DISCOVER_REVIEW      = "character_profiles_discover_review"
  ```
- **第 104-114 行 `_REVIEW_TYPE_TO_INTERRUPT_TYPE`** 新增映射：
  ```
  "character_profiles_discover": InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW,
  ```

### `src/novel_workflow/subgraph.py`
- **第 11-29 行 imports**：追加 `CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT`。
- **第 40-55 行 `_HISTORY_MAX_ROUNDS`**：新增 `"character_profiles_discover": 3,`（宽松 + 每章一次，3 轮控 token）。
- **第 77-113 行 `_REGEN_OUTPUT_HINTS`**：**新增一条**，覆盖默认的"从正文第一句话开始输出"（那句话会误导 LLM 把 discover 输出当章节正文）：
  ```
  "character_profiles_discover": (
      "直接输出修改后的完整【人物档案 markdown】，"
      "不是章节正文；不得描述你做了哪些修改、不得使用元叙述语言。"
      "必须保留输入档案中所有原有角色条目原样，只追加或在原条目末尾补充。"
  )
  ```
- **第 116-131 行 `_REVIEW_PROMPTS`**：新增 `"character_profiles_discover": CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT,`
- **第 35 行 `_EVOLVABLE_REVIEW_TYPES`**：**不改**（不接入进化机制，见决策 8）。

### `src/novel_workflow/prompts/__init__.py`
- **第 51-58 行 scene_beats 段落**后追加：
  ```
  from noval_workflow.prompts.character_profiles_discover import (
      CHARACTER_PROFILES_DISCOVER_PROMPT,
      CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT,
      character_profiles_discover_prompt,
  )
  ```
- **第 128-134 行 `__all__` 里 scene beats 段落之后**追加三个名称。

### `frontend/src/lib/interruptTypes.ts`
- **第 50 行 `SCENE_BEATS_REVIEW` 之后**新增（字符串值必须与后端一字不差）：
  ```
  CHARACTER_PROFILES_DISCOVER_ENTRY_GATE:      "character_profiles_discover_entry_gate",
  CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT: "character_profiles_discover_direction_input",
  CHARACTER_PROFILES_DISCOVER_REVIEW:          "character_profiles_discover_review",
  ```
- **第 251-298 行 `TYPE_TO_FORM`** 新增三行：
  ```
  [InterruptType.CHARACTER_PROFILES_DISCOVER_ENTRY_GATE]: "entry_gate",
  [InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT]: "direction",
  [InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW]: "human_review",
  ```
- **第 320-327 行 `DIRECTION_TITLE`** 追加登记（`ask_direction=False` 不触发，但为一致性登记，避免万一未来打开时前端显示"调整方向"通用回退）：
  ```
  [InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT]: "角色档案发现调整方向",
  ```

### `frontend/src/lib/types.ts`
- **第 118-135 行 `REVIEW_TYPE_LABELS`** 追加：
  ```
  character_profiles_discover: "角色档案发现",
  ```
- **第 145 行 `EVOLVABLE_REVIEW_TYPES`**：**不改**（不接入进化，见决策 8）。

---

## 三、跳过 / 空回车行为

`edit_step_subgraph.py:141-148 step_entry` 已内建 `_SKIP_WORDS`（含空字符串）。空回车 / `no` / `否` / `skip` → 整个子图直接 END → 父图继续 `chapter_edit_subgraph`，`state.character_profiles` 无变化。

`_ENTRY_HINT` 文案（放在 `character_profiles_discover_subgraph.py` 模块级常量，格式对齐 `scene_beats_subgraph.py:39`）：
```
\n\n---\n· 直接回车 / 输入 no 或 否 → 跳过（本章无需更新角色档案）\n· 输入其他内容（例如 yes） → 进入发现流程\n\n提示：若本章无新角色出场且已知角色未暴露新信息，建议直接跳过；本步骤走一次约需 30 秒生成 + 用户审核。
```

首章无特殊 skip 逻辑——由用户在 gate 处自行判断（一般首章角色都在 Phase 1 初版档案里，用户空回车即可）。

---

## 四、验证方案

### 后端 pytest（新建 `tests/unit_tests/test_character_profiles_discover.py`）
参照 `tests/unit_tests/test_scene_beats.py` 布局，至少覆盖：
1. `_prepare_character_profiles_discover` 返回字典包含 `system_context / task_prompt / review_type == "character_profiles_discover"`；`task_prompt` 同时嵌入 `existing_profiles` 与 `chapter_draft`。
2. `_save_character_profiles_discover`：非空 draft → 返回 `{"character_profiles": draft}`；空 draft → 返回 `{}`（不 clobber 原字段）。
3. `character_profiles_discover_prompt`：占位符替换正确、`{chapter_num}` = `state.total_chapters_written + 1`。
4. `interrupt_types.review_type_to_interrupt_type("character_profiles_discover") == CHARACTER_PROFILES_DISCOVER_REVIEW`。
5. `subgraph._REVIEW_PROMPTS["character_profiles_discover"]` 存在，且断言其正文**不含** `CHARACTER_PROFILES_REVIEW_PROMPT` 的"力量体系归属 / 卡司配额 / 双层人设"关键词——防未来误串接。

跑法：`cd 项目根 && pytest tests/unit_tests/test_character_profiles_discover.py -v`。

### 端到端手动（`make dev-backend` + `make dev-frontend`）
从任一已进入 Phase 2 的 thread（或走 `make dev-fresh` 从头跑到第 1 章正文过审）：
1. 章正文过审 → 观察是否停在 `character_profiles_discover_step` 的 entry_gate（前端右侧栏出现 `EntryGateForm`，标题"是否根据本章正文发现新角色 / 补充已知角色档案？"）。
2. **空回车 skip**：thread 直接进入 `chapter_edit_subgraph.arc_step`；`getThreadState().values.character_profiles` 无变化。
3. **输入 `yes` → 走完 discover**：generate → llm_self_review → human_review interrupt。前端 `HumanReviewForm` 顶部标题"角色档案发现"（`REVIEW_TYPE_LABELS`），textarea 展示 LLM 输出的合流后完整档案，肉眼验证：原档案条目全部保留，新增段挂在末尾或原条目内。
4. **空回车通过** → save 写回；`getThreadState().values.character_profiles` 已更新。
5. **反馈打回**：输入"XX 角色应归属北境势力" → 观察是否走一轮 regen → 新 draft 是否落实反馈。
6. **回流验证**：走到下一章 `save_titles → scene_beats_step → prepare_chapter`，从 `system_context` 里的【人物档案】能读到刚新增的角色（可通过 LLM 生成日志的 `system_context` dump 观察，或直接读 `getThreadState().values.character_profiles`）。

---

## 五、风险 & 明确不做的事

**风险 1 · 一致性冻结冲突**：`consistency.py::audit_consistency / revise_consistency` 只在 Phase 1 → `save_config` 之间跑一次（`graph.py:224-234`），Phase 2 不复审。discover 在 Phase 2 修改 `character_profiles` **不违反冻结契约**（"冻结"指进入正式创作前须一致，发现阶段是显式扩展面）。**本次不加**"discover 后的 mini-consistency 复审"。

**风险 2 · 每章成本**：每章多一次 LLM generate + self_review + 人工。token 约 +30%（全量重吐档案），用户操作 +1~2 次。对冲方式：entry_gate 文案默认建议"跳过"，用户对本章无新角色时一次空回车带过（不跑 LLM，成本可忽略）。

**风险 3 · 首章特例**：首章 `character_profiles` 是 Phase 1 初版（已含全主要角色），首章往往就是主要角色首次亮相，理论上无新发现。**不加特殊 skip**——交给 gate 引导用户自决。即便走一遍 discover，也只会追加"本章戏份记录"式段落，无破坏性。

**明确不做**（避免范围爬升）：
1. 不改 `state.character_profiles` 字段类型（保持 `str`，不引入 `discovered_characters` 结构化字段）。
2. 不加前端专用组件（`CHARACTER_PROFILES_DISCOVER_REVIEW → human_review` FormKind = 复用 `HumanReviewForm`）。
3. 不接入进化机制（`_EVOLVABLE_REVIEW_TYPES` / `EVOLVABLE_REVIEW_TYPES` / `_REVIEW_TYPE_TO_EVOLVED_FIELD` 均不改）。
4. 不改 `save_character_profiles`（`nodes/foundation.py:126-127`）—— Phase 1 初版落盘链路完全不动。
5. 不做 delta 算法 / 代码合流——LLM 全量输出即写回。
6. 不做 before/after side-by-side diff UI（差异化界面属范围爬升）。
7. 不做旧 thread 迁移——新 thread 从建立即走新链路；老 thread 从下一次章末进入即为纯增量。
8. 不加"跳过判断的正则启发"——完全由用户 gate 决策。

---

## 六、关键文件清单

**新建**：
- `src/novel_workflow/character_profiles_discover_subgraph.py`
- `src/novel_workflow/nodes/character_profiles_discover.py`
- `src/novel_workflow/prompts/character_profiles_discover.py`
- `tests/unit_tests/test_character_profiles_discover.py`

**修改**（file:line 精准锚点）：
- `src/novel_workflow/graph.py:65 / 135 / 265`
- `src/novel_workflow/interrupt_types.py:70 之后 / 104-114`
- `src/novel_workflow/subgraph.py:11-29 / 40-55 / 77-113 / 116-131`
- `src/novel_workflow/prompts/__init__.py:51-58 / 128-134`
- `frontend/src/lib/interruptTypes.ts:50 之后 / 251-298 / 320-327`
- `frontend/src/lib/types.ts:118-135`
