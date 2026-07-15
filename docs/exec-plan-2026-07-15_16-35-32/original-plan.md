# 引入「卷（Volume）」作为结构化中间层

## Context

**问题**：`overall_outline`（整书大纲）里作者/LLM 会用「第一卷 / 第二卷 / 第三卷 / 第四卷」组织顶层结构，但在代码里**分卷只是 markdown 自由文本中的文字段落**——没有任何字段、参数、映射把「卷」提升为一等结构：

- `NovelState` 无 `volumes / volume_ranges / current_volume` 字段
- `ChapterPlanItem` 无 `volume` 字段
- `chapter_plan_prompt`（前瞻 40 章）、`arc_outline_prompt`（批级 5 章）、`chapter_prompt`（章节正文）三处 prompt **均未注入卷信息**
- `arc_outline_prompt` 的【本批位置卡】只有 `batch_start / batch_end / done / total_word_count / plan_coverage_note`——**没有"当前第几卷、卷内位置、卷边界"**
- 章 → 卷 无映射函数（没有任何代码能回答"第 37 章属于第几卷"）

**症状**：
- 前瞻 40 章的 `chapter_plan` 生成时 LLM 不知道这 40 章会不会跨卷、跨到哪一卷——**长期规划失锚**
- 批级 5 章的 `arc_outline` 不知道当前在卷首/卷中/卷尾——**短期节奏失锚**
- 章节正文生成时不知道"是本卷收尾章"还是"新卷开卷章"——**基调与埋钩失锚**

**已定方向**（用户确认）：
1. 混合 gate（AI 推荐 + 人工确认 + 可回改）——业界主流"硬边界写死"与"完全 AI 动态"都不采用
2. **弹性 range 模型**：卷起始章号锁定，卷结束章号弹性（`target_min / target_max`，实际以剧情为准）
3. 卷数量按 `overall_outline` 的实际分卷规划（当前默认 4 卷，暂时不改这块 prompt）
4. `target_min / target_max` 由用户在 `review_volumes` 时手工写
5. **边界穿越触发 gate**：`prepare_chapter_plan` 时若本批 `[start, end]` 窗口穿越某卷 `target_min / target_max`（有任一落入窗口），弹 `VOLUME_BOUNDARY_GATE` 让用户确认「继续本卷 / 在第 X 章收卷 / 延长 target」，用户决策后再规划
6. 前端顶部 4 卷横条呈现（当前卷高亮 + 已完成 ✓ + target range 徽章）

**行业依据**：
- 主流产品（Novelcrafter/Sudowrite/Plottr/Scrivener/Squibler）无一采用硬边界，均支持拖拽 + 事后可改；但**均未提供"target range"字段**——LLM 拿不到节奏参考
- 学术侧 Re3 的 `continuation-threshold`、WriteHERE 的 recursive planning 支持动态边界
- 写作方法论（Save the Cat 的 "Fun & Games 20-50%"）原生支持 range 而非点位

方案取"业界拖拽共识 + LLM 规划信号"的折中：**卷起点硬 + 卷终点弹性 range + 边界事件触发 gate**。

---

## 一、后端改动

### 1.1 数据模型（`src/novel_workflow/state.py`）

新增 `Volume` dataclass，加到 `NovelState`：

```python
@dataclass
class Volume:
    """整书分卷条目——横向大结构，位于 overall_outline 之下、chapter_plan 之上。

    弹性 range 语义：chapter_start 锁定；结束边界由 target_min/target_max 表达
    软约束；actual_end 只有在 VOLUME_BOUNDARY_GATE 用户点「在此收卷」后才写入，
    在此之前 = None（当前卷进行中）。

    章 → 卷映射由 volume_of_chapter(chapter_num, volumes) 提供，规则：
      - 已收卷（actual_end != None）：chapter ∈ [chapter_start, actual_end]
      - 当前进行中（actual_end == None）：chapter >= chapter_start 且属于最靠前的未收卷
    """
    index: int                     # 第几卷（1-based）
    title: str                     # 卷名，如「第一卷 · 少年入宗」
    summary: str = ""              # 本卷主线目标 & 情绪基调（≤80 字）
    setup_for_next: str = ""       # 卷尾要为下一卷埋的钩（≤60 字，最后一卷可空）
    chapter_start: int = 1         # 起始章号（1-based，硬锁定）
    target_min: int = 0            # 目标下限（软约束）
    target_max: int = 0            # 目标上限（软约束）
    actual_end: int | None = None  # 实际收卷章号，None = 仍在进行中
    status: str = "planning"       # planning | in_progress | closed
```

在 `NovelState` 里新增（放 `overall_outline` 附近）：
```python
volumes: list[Volume] = field(default_factory=list)
# 分卷规划：从 overall_outline 抽取，弹性 range 模型。
# 覆盖语义：save_volumes 全量覆盖返回；不使用 operator.add（用户可能删卷/合并）
```

### 1.2 章 → 卷映射工具（新文件 `src/novel_workflow/volume_utils.py`）

```python
def volume_of_chapter(chapter_num: int, volumes: list[Volume]) -> Volume | None:
    """回答"第 N 章属于第几卷"。已收卷按 [start, actual_end] 判断；
    当前进行中卷按 chapter_num >= chapter_start 且是最靠前的未收卷。"""

def current_volume(volumes: list[Volume], total_chapters_written: int) -> Volume | None:
    """当前活跃卷 = status == in_progress 的第一卷（或按章号推断）。"""

def volume_position_card(state: NovelState) -> str:
    """生成"当前卷位置卡"markdown 片段，供三处 prompt 头部注入。
    格式：
        【当前卷位置】
        - 当前所在：第 K 卷《{title}》（第 {chapter_start} 章起，target {min}-{max} 章）
        - 本卷进度：已完成本卷 {n_done_in_vol}/({target_min}~{target_max}) 章
        - 上一卷：{prev.title} —— {prev.summary}
        - 本卷主线：{cur.summary}
        - 卷尾 setup：{cur.setup_for_next}
        - 下一卷预告：{next.title if next else "（本卷为终卷）"}
    """

def find_boundary_crossings(
    window_start: int,
    window_end: int,
    volumes: list[Volume],
) -> list[dict]:
    """判断 [window_start, window_end] 是否穿越任一卷的 target_min / target_max。
    返回穿越点列表，每项 {volume_index, kind: 'target_min'|'target_max', chapter}。
    供 route_before_chapter_plan 决定是否弹 VOLUME_BOUNDARY_GATE。"""
```

### 1.3 新节点：`prepare_volumes` / `save_volumes`（新文件 `src/novel_workflow/nodes/volumes.py`）

- **位置**：`save_overall_outline` 之后、`prepare_character_profiles` 之前（或紧接 `overall_outline` 保存）
- **prepare_volumes**：
  - LLM 从 `state.overall_outline` 抽取分卷结构 → JSON 列表 `[{index, title, summary, setup_for_next, chapter_start, target_min, target_max}]`
  - 提示词强调：`chapter_start` 顺次拼接（第一卷从 1 开始，之后各卷 = 前卷 `target_max + 1` 作为**建议起点**），`target_min/target_max` 由 LLM 从 overall_outline 里推荐（例如"约 25 章"→ min=22, max=28）
  - 写入 `state.current_draft`（JSON 字符串），`review_type = "volumes"`
- **save_volumes**：解析 JSON → 逐条 `Volume(**item)`，第一卷 `status="in_progress"` 其余 `status="planning"`，写回 `state.volumes`
- 走通用 `review_subgraph`（复用现有 human_review 流程；前端渲染由 `HumanReviewForm` + 新增专用 payload 支持）

**Prompt 提示词**（放 `prompts/base.py` 新增 `volumes_prompt` 方法 + `render_volumes_prompt`）：
- 从 `overall_outline` 抽结构；如果 overall_outline 里已明文写"共 4 卷"或"第 X 卷"，严格按其分；否则默认按整书目标篇幅推测 3-5 卷
- 输出 JSON schema 严格约束（照 `chapter_plan` 的 JSON 输出模板）

### 1.4 `route_before_chapter_plan` + `VOLUME_BOUNDARY_GATE`（改 `src/novel_workflow/graph.py`）

**当前主链**（`graph.py:281-283`）：
```
save_chapter (loop end) → chapter_plan_or_arc → prepare_chapter_plan → review_chapter_plan → save_chapter_plan → prepare_arc_outline
```

**新主链**（在 `prepare_chapter_plan` 之前插 gate 节点）：
```
save_chapter → chapter_plan_or_arc → volume_boundary_gate → prepare_chapter_plan → ...
                                        ↓ (无穿越)
                                     直接 pass 到 prepare_chapter_plan
```

**新节点** `volume_boundary_gate`（新文件 `src/novel_workflow/nodes/volume_gate.py`）：
```python
def volume_boundary_gate(state: NovelState) -> dict:
    """判断本次 chapter_plan 窗口是否穿越卷边界；穿越则 interrupt。
    窗口 = [total_chapters_written + 1, total_chapters_written + CHAPTER_PLAN_WINDOW]
    穿越判定 = 有任一 volume 的 target_min 或 target_max 落入该窗口。
    """
    window_start = state.total_chapters_written + 1
    window_end = window_start + CHAPTER_PLAN_WINDOW - 1
    crossings = find_boundary_crossings(window_start, window_end, state.volumes)
    if not crossings:
        return {}  # 无穿越，pass

    # 有穿越 → interrupt，让用户三选一
    payload = {
        "type": InterruptType.VOLUME_BOUNDARY_GATE,
        "window": [window_start, window_end],
        "crossings": crossings,   # [{volume_index, kind, chapter}]
        "current_volume": current_volume(state.volumes, state.total_chapters_written).to_dict(),
        "message": "本次长期规划范围将穿越卷边界，请确认：",
        "options": [
            {"action": "continue_current",  "label": "继续本卷（不改边界）"},
            {"action": "close_at",          "label": "在第 X 章收卷（AI 建议 X 值，用户可改）"},
            {"action": "extend_target_max", "label": "延长本卷 target_max 到 N（用户填）"},
        ],
    }
    decision = interrupt(payload)
    # 根据 decision 更新 state.volumes:
    #   continue_current → 无变化
    #   close_at → 目标卷 actual_end = X, status = closed; 下一卷 status = in_progress
    #   extend_target_max → 目标卷 target_max = N
    return {"volumes": updated_volumes}
```

`InterruptType` 新增枚举值：
```python
VOLUME_BOUNDARY_GATE = "volume_boundary_gate"
```

`_REVIEW_TYPE_TO_INTERRUPT_TYPE` 新增：
```python
"volumes": InterruptType.REVIEW_GENERIC,  # volumes 走通用 review 表单
```

### 1.5 三处 prompt 注入「当前卷位置卡」

在生成 `chapter_plan`、`arc_outline`、`chapter` 时，prompt 头部注入 `volume_position_card(state)` 的返回值：

- **`chapter_plan_prompt`**（`prompts/base.py:720-1051` 附近）：在【本批位置卡】等价段落前面新增【当前卷位置】——让 LLM 规划 40 章时知道这些章跨卷情况（含"哪些章属于本卷、哪些章属于下一卷 setup"）
- **`arc_outline_prompt`**（`prompts/base.py:649-668`）：扩展现有【本批位置卡】，在头部叠加卷位置卡
- **`chapter_prompt`**（`prompts/base.py:472-615`）：新增一段"【当前卷】{title} · 本章为卷内第 M/N 章（{位置类型：卷首/卷中/卷尾}）"，让正文层感知卷内定位（尤其卷首、卷尾章需要区分基调）

`build_foundation_context`（`src/novel_workflow/context.py`）不改——避免整个 system_context 都塞卷信息，只让**具体生成节点**在 task_prompt 里注入位置卡。

---

## 二、前端改动

### 2.1 类型定义（`frontend/src/lib/types.ts`）

```typescript
export interface Volume {
  index: number;
  title: string;
  summary: string;
  setup_for_next: string;
  chapter_start: number;
  target_min: number;
  target_max: number;
  actual_end: number | null;
  status: "planning" | "in_progress" | "closed";
}

export interface NovelState {
  // ... 现有字段
  volumes: Volume[];
}

// REVIEW_TYPE_LABELS 新增
volumes: "分卷规划",
```

### 2.2 顶部 4 卷横条（`frontend/src/components/novel/VolumeRibbon.tsx` 新增）

在 `NovelWorkspace.tsx` 顶部（`NovelDetail` 之上）插入横条组件：

```
┌────────────────────────────────────────────────────────────────┐
│  ✓ 卷一 少年入宗   ●卷二 出山历练   ○ 卷三 …   ○ 卷四 …        │
│    1-24  24章       25-…  已3/(20~30)                          │
└────────────────────────────────────────────────────────────────┘
```

- 从 `state.volumes` 读；当前卷（`status="in_progress"`）高亮加粗
- 已收卷（`status="closed"`）打勾 + 显示 `chapter_start-actual_end` 实际范围
- 进行中卷显示 `chapter_start-...` + `已 N/(target_min~target_max) 章` 徽章
- 未开启卷显示 `chapter_start-...` + target range 徽章（虚线）
- 点击卷标签 → 打开该卷详情弹窗（title / summary / setup_for_next 只读）
- 编辑入口：只在 `HumanReviewForm` 走 `review_type=volumes` 或 `VOLUME_BOUNDARY_GATE` 时通过对应表单编辑；顶部横条本身只读

### 2.3 volumes review 表单（`frontend/src/components/interrupts/VolumesReviewForm.tsx` 新增）

- `review_type=volumes` 时走这个专用表单（在 `interruptTypes.ts` 的 `TYPE_TO_FORM` 里加映射；或直接扩展 `HumanReviewForm` 里对 volumes 类型的渲染）
- 展示 LLM 抽出的卷列表，每卷一个可编辑卡片：title / summary / setup_for_next / target_min / target_max
- `chapter_start` 由前卷 `target_max + 1` 自动推算（只读，用户改前卷 target_max 时自动重算）
- 提交时 JSON 序列化写回 `current_draft`，走通用 review 逻辑

### 2.4 VOLUME_BOUNDARY_GATE 表单（`frontend/src/components/interrupts/VolumeBoundaryGateForm.tsx` 新增）

- 展示：当前卷信息 + 穿越点说明（"本次长期规划范围 [21, 60] 穿越卷一 target_max=25"）
- 三选一按钮：
  - **继续本卷**（默认高亮）
  - **在第 [X] 章收卷** —— AI 建议章号（`target_min` 与 `target_max` 之间的中位）+ 数字输入让用户改
  - **延长本卷 target_max 到 [N]** —— 数字输入，默认 `target_max + 5`
- 提交时通过 LangGraph resume payload 回传决策，`volume_boundary_gate` 节点消费

### 2.5 前端类型契约（`frontend/src/lib/interruptTypes.ts`）

```typescript
export const InterruptType = {
  // ... 现有
  VOLUME_BOUNDARY_GATE: "volume_boundary_gate",
} as const;

// TYPE_TO_FORM 映射
[InterruptType.VOLUME_BOUNDARY_GATE]: "VolumeBoundaryGateForm",
```

---

## 三、关键文件清单

**新增**：
- `src/novel_workflow/volume_utils.py` — 章卷映射 + 位置卡渲染 + 穿越判定
- `src/novel_workflow/nodes/volumes.py` — prepare_volumes / save_volumes
- `src/novel_workflow/nodes/volume_gate.py` — volume_boundary_gate 节点
- `frontend/src/components/novel/VolumeRibbon.tsx` — 顶部 4 卷横条
- `frontend/src/components/interrupts/VolumesReviewForm.tsx`
- `frontend/src/components/interrupts/VolumeBoundaryGateForm.tsx`

**修改**：
- `src/novel_workflow/state.py` — 加 `Volume` dataclass + `volumes` 字段
- `src/novel_workflow/interrupt_types.py` — 加 `VOLUME_BOUNDARY_GATE` 枚举 + `volumes` review_type 映射
- `src/novel_workflow/graph.py` — 把 `prepare_volumes/review_volumes/save_volumes` 插在 `save_overall_outline` 之后；在 `chapter_plan_or_arc` 与 `prepare_chapter_plan` 之间插 `volume_boundary_gate`
- `src/novel_workflow/prompts/base.py` — 加 `volumes_prompt` / `render_volumes_prompt`；`chapter_plan_prompt`、`arc_outline_prompt`、`chapter_prompt` 头部注入 `volume_position_card`
- `frontend/src/lib/types.ts` — 加 `Volume` 类型 + `NovelState.volumes` + `REVIEW_TYPE_LABELS.volumes`
- `frontend/src/lib/interruptTypes.ts` — 加 `VOLUME_BOUNDARY_GATE` + 表单映射
- `frontend/src/components/NovelWorkspace.tsx` — 顶部挂 `<VolumeRibbon />`

---

## 四、可复用的现有组件/函数

- `review_subgraph` — 直接复用于 `review_volumes`（通用 review 流程 + human_review 循环）
- `interrupt()` + `_REVIEW_TYPE_TO_INTERRUPT_TYPE`（`interrupt_types.py:119`）— 复用契约式 interrupt 派发
- `_extract_chapter_plan_range`（`prompts/base.py`）— 章号切片工具，同类逻辑可用于 `find_boundary_crossings`
- `ChapterPlanCards.tsx` / `chapterPlanMeta.ts` — 参考其"逐条卡片渲染 + intensity 徽章"范式做卷列表卡片
- `ChapterPlanReadonly.tsx`（`StateEditPanel` 尾部）— 参考其"只读观测段"做卷只读视图
- `GraphView.layout.ts` 的 `PhaseKey` — 后续可选：给 `prepare_volumes / volume_boundary_gate` 加节点色（不阻塞本次落地）
- `EntryGateForm.tsx` — 参考其单选按钮组模式做 `VolumeBoundaryGateForm`

---

## 五、验收路径

### 5.1 自动化门禁
```
uv run pytest -x -q                        # 后端全量单测（含 state 序列化 / graph 装配）
uv run pyright                             # 后端类型检查
cd frontend && pnpm tsc --noEmit           # 前端类型检查
cd frontend && pnpm lint                   # 前端 lint
```

新增单测：
- `tests/test_volume_utils.py` — `volume_of_chapter` 边界 case（当前卷 / 已收卷 / 未开启卷）；`find_boundary_crossings` 穿越 target_min / target_max / 两者都穿 / 都不穿；`volume_position_card` 首卷/中卷/末卷渲染
- `tests/test_volumes_node.py` — `prepare_volumes` JSON schema 验证 + `save_volumes` 反序列化容错（缺字段走默认）
- `tests/test_volume_boundary_gate.py` — 三种 decision 分支各自更新 state 是否正确

### 5.2 手工端到端验收

**场景 A：新建小说走到分卷 review**
1. `make dev` 启动前后端
2. 走脑爆 → 基础设定 → overall_outline 生成通过
3. **应观察**：进入 `VolumesReviewForm`，LLM 抽出 4 卷（title/summary/setup_for_next/target_min/target_max），用户编辑后提交
4. **应观察**：顶部 `VolumeRibbon` 出现 4 卷横条，第一卷高亮 `in_progress`，其余 `planning`

**场景 B：跑到第一次 chapter_plan 触发 gate**
1. 继续生成人物档案 → 走到第一次 `prepare_chapter_plan`
2. 假设 `total_chapters_written=0`, `CHAPTER_PLAN_WINDOW=40`, 第一卷 `target_min=20 target_max=25`
3. **应观察**：`window=[1,40]` 穿越卷一 `target_max=25` → `VolumeBoundaryGateForm` 弹出，展示"卷一 · target_max=25 落入本次规划窗口"
4. 用户选"继续本卷" → chapter_plan 生成，40 条条目里 26-40 章的 purpose 应体现"卷二铺垫" 语义（LLM 拿到了卷位置卡）
5. **应观察**：生成完的 chapter_plan 里，第 25 章的 `ending_hook` 应含卷一 `setup_for_next` 元素；第 26 章 `purpose` 应带"卷二开启"意味

**场景 C：卷边界调整回改**
1. 写到第 22 章，用户在 `chapter_plan` review 时手动打回，或走到下次 chapter_plan 时选择"在第 23 章收卷"
2. **应观察**：`state.volumes[0].actual_end=23, status="closed"`；`state.volumes[1].chapter_start=24, status="in_progress"`
3. 下一次 `arc_outline_prompt` 位置卡应显示"当前所在：第 2 卷 · 第 24 章起"
4. 顶部横条：卷一变 ✓ 显示 `1-23`，卷二变高亮

**场景 D：arc_outline 拿到卷位置**
1. 用 chrome-devtools MCP 或直接读 LangGraph state.next 前的 task_prompt（可通过后端 log）
2. **应观察**：`arc_outline` 的 task_prompt 头部含【当前卷位置】段，字段完整

### 5.3 用户可复现验收步骤

用户按此步骤走一遍即算通过：
1. 新建小说，走脑爆 + 基础设定
2. 到达"分卷规划"审核 → 看到 4 卷卡片，编辑 target_min/target_max → 提交
3. 顶部出现 4 卷横条，第一卷高亮
4. 继续推进到第一次 chapter_plan → 出现"卷边界穿越"提示 → 选"继续本卷"
5. chapter_plan 生成后，检查靠近卷一 target_max 的章条目是否有"卷尾节奏"迹象
6. 观察 arc_outline 生成期，本批位置卡里应含【当前卷位置】
7. 到达卷一 target_min 附近时（触发下次 chapter_plan gate），选"在第 X 章收卷"→ 横条更新 → 第二卷激活

**注意**：本次改动同时涉及 state schema、graph 拓扑、prompt、前端 UI，属于**跨前后端跨图的结构性改动**。触发闸门 A（编码前 checklist）、闸门 E（关键假设需先验证：如"LLM 从 overall_outline 抽卷"能否稳定输出合规 JSON——建议先用最小脚本跑一次 `prepare_volumes` 提示词看输出）。建议用 `execute-plan-plus` 分批推进，先落 1.1-1.3（数据模型 + 抽卷节点 + volume_utils）跑通再进 1.4-1.5（gate + prompt 注入），最后前端。
