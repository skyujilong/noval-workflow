# 次要角色「提升为重要角色」功能方案（Part 2）

> 背景：Part 1（提示词修复）已完成——人物卡的深层设计（`hidden_persona` / `arc_trajectory` /
> `ability_contract`）从「全员强制」改为「按 `role` 条件触发」。副作用是：章节中途由
> `entity_cards_step` / `entity_discover_step` 建的角色多为 `次要角色`，天生**没有**深层字段。
> 当剧情推进、某个次要角色戏份变重时，需要一条把它「提升为重要角色」并补齐深层设计的路径。
> 本方案即该功能。**Part 1 是本功能的地基**（深层字段可选、渲染端空值跳过均已就绪）。

---

## 〇、已锁定的设计决策（用户确认）

| 决策点 | 选定方案 |
|---|---|
| 触发方式 | **人工手动提升**——人在卡库/人物档案界面对某个 `次要角色` 主动发起 |
| 深层字段补齐 | **LLM 聚焦生成 → 人工审改**——发一次聚焦 prompt 生成草稿，人工改后落库 |
| 接入架构 | **`http_app.py` sidecar 双端点**——带外操作，不塞进线性主图 |

---

## 一、为什么走 sidecar，而不是主图子流程

主图（`graph.py`）是 `brainstorm_gate` 单入口的**线性章节管线**，运行时通常停在章节循环中途的某个
interrupt 上。「提升」是**人随时发起的带外操作**，与章节进度正交：

- **塞进主图**（`prepare_promote → review_promote → save_promote` 复用 `review_subgraph`）：
  能白嫖图的 interrupt / HumanReviewForm 审改机制，但需要给线性图开一个「带外入口」，在
  mid-loop 注入绕路——**难维护、易与章节循环状态打架**。
- **走 sidecar**（本方案）：`http_app.py` 已有大量带外 state 操作先例（prompt-evolution apply、
  novels summary 经 lg client 读 thread）。提升端点与主图**完全正交**，不扰动 checkpointer 的章节
  进度。代价：审改 UX 由前端复用现有可编辑卡组件搭，而非复用图的 interrupt。

**结论：sidecar 更贴「带外」本质，更好维护。** 审改 UX 可复用前端既有的 `editableState` / 卡片
JSON 编辑组件，损失有限。

---

## 二、数据契约（零 schema 改动）

- 提升 = **canon 变更**：`role`（`次要角色` → 人工选定的目标重要角色）+ 补齐 `appearance` 加厚 /
  `hidden_persona` / `arc_trajectory` / `ability_contract`。
- `entity_cards` 在 `state.py` 是**覆盖语义**（无 `operator.add`）→ 保存端读全量卡库、就地改中目标
  卡、`update_state` 回传**全量新列表**替换。
- **无需改模型**：这些字段在 `CharacterCard` 本就 `default=""`，仅 `role` 必填且目标卡已有值。
- **不借道 `UPDATABLE_FIELDS`**：那是章末 `entity_discover` 动态字段更新的白名单（motivation/
  current_state/relations），canon 不在其中。提升是**独立的 canon 变更路径**，直接改卡，不走白名单。

### 目标 role 取值（人工选定）
`主要配角` / `功能性反派` / `根源反派` / `感情线角色`（即 `CharacterRole` 去掉 `主角` 与 `次要角色`）。

---

## 三、后端改动

### 3.1 `prompts/entity_cards.py` — 新增 `promote_character_prompt(state, card, target_role)`

聚焦**单角色**的深层设计补全 prompt。

- **输入上下文**：
  - 该角色**现状卡**（name/role/summary/appearance/personality/abilities/motivation/
    current_state/relations）——保连续性，别推翻已建立的设定；
  - **全书 canon**：世界观 / 力量体系 / 核心冲突 / 整体大纲 / 分卷（供四卷弧光、契约落体系）；
  - 目标 `role`（决定弧光/契约的分层口径，如根源反派 vs 感情线角色）。
- **输出**：严格 JSON，**只含**要补/改的字段：
  `{"role", "appearance", "hidden_persona", "arc_trajectory", "ability_contract"}`
  （其余字段不动；`appearance` 若原本太薄则加厚为体貌基线）。
- **口径复用 Part 1**：四卷弧光只写大势、契约落力量体系 + 触发/反噬、命名/外貌规则一致，保证提升后
  的卡与 Phase-1 卡司**同质**。

### 3.2 `http_app.py` — 两个路由

#### `POST /character/promote/draft`
- 入参：`{thread_id, name, target_role}`
- 流程：lg client `get_state(thread_id)` 读 `entity_cards` → 定位目标卡 → 组装 canon 上下文 →
  跑 `promote_character_prompt` → 返回 draft JSON。
- **fail-loud**（符合 CLAUDE.md 不静默兜底）：目标卡不存在 / 不是 `次要角色` / `target_role`
  非法（不在 4 个可选值内）→ 明确 4xx，不静默。

#### `POST /character/promote/apply`
- 入参：`{thread_id, name, card_patch}`（`card_patch` 是人工审改后的终稿字段）
- 流程：`get_state` 读**全量** `entity_cards` → 定位目标卡 → 用 `card_patch` 覆盖 role + 4 字段 →
  `parse_card` 重新校验合法（role 枚举、字段合规，非法即抛）→ `update_state(thread_id,
  values={"entity_cards": 全量新列表})` 落库。
- **fail-loud**：`parse_card` 校验失败（如 role 非法）直接抛错返回，不写坏数据。

---

## 四、前端改动（`frontend/`，TS/React）

### 4.1 提升入口
在卡库只读视图（`components/state/EntityCardsReadonly.tsx` 或其在 `NovelDetail.tsx` 的包裹处），
给 `role === "次要角色"` 的人物卡加一个「提升为重要角色」按钮 + 目标 role 选择器
（4 个可选值，用**判别式选项**，不用一堆 boolean）。

### 4.2 提升审改流（新组件 `PromoteCharacterPanel`）
点提升 → 调 `/draft` → 拿 LLM 草稿 → **复用现有可编辑卡审改 UI**（`lib/editableState` /
卡片 JSON 编辑）让人工改 → 调 `/apply` 落库 → 刷新卡库。

### 4.3 React skill 约束
- 逻辑抽进 `usePromoteCharacter` hook（draft / 编辑中 / applying / 错误 的状态机），
  `PromoteCharacterPanel` 保持声明式；
- 目标 role 用判别式类型，不用可选 boolean 堆叠；
- 组件超过 ~150 行或 JSX 深嵌套就拆分。
- **无 types 改动**：`EntityCard` 接口已含全部相关字段（Part 1 前的前端重构已补齐）。

---

## 五、不改什么

- 主图 `graph.py` / `review_subgraph` **不动**（提升走 sidecar，不进图）。
- `UPDATABLE_FIELDS` 白名单**不动**（章末动态更新的兜底，与提升的 canon 路径无关）。
- 模型层 `state.py` **不动**（字段已 `default=""`）。
- 前端 `types.ts` **不动**（字段已齐）。

---

## 六、验证

- **后端**：`PYTHONPATH=src .venv/bin/python` 导入 + 打印 `promote_character_prompt` 目视；
  起 http_app，对一个测试 thread 跑 `/draft` → `/apply`，`get_state` 确认目标卡 role/深层字段已
  更新、**其余卡未动**；非法 target_role / 非次要角色 / parse 失败均返回明确错误。
- **前端**：`node_modules/.bin/tsc -b --force` 通过；dev server 手测提升流
  （次要角色 → 选目标 role → `/draft` 出草稿 → 审改 → `/apply` 落库 → 卡库刷新显示新 role + 深层字段）。

---

## 七、实现顺序建议

1. 后端 `promote_character_prompt`（可独立打印验证）
2. 后端两个端点 + fail-loud 校验
3. 前端 `usePromoteCharacter` hook + `PromoteCharacterPanel`
4. 前端提升入口按钮接线
5. 端到端手测

---

## 附：仍可回退的架构点

若后续更希望**复用图的 review gate**（HumanReviewForm 的成熟审改体验），可把 Part 2 改成主图带外
子流程（代价是主图开带外入口）。本方案默认 sidecar；此点保留，改动集中在第一、三节。
