# 小说创作工作流重构方案

## 目标

将当前简单的「生成 → 审核」两节点循环，重构为完整的小说创作流水线：

- **第一阶段（基础设定）**：5 个 LLM 生成环节，每个环节均有 LLM 自审 + 人工审核
- **第二阶段（章节创作循环）**：每批生成 5 章标题 → 逐章写作 → 保存到本地文件 → 询问是否继续

---

## 整体架构

### 核心设计：可复用的审核子图

「生成 → LLM 自审 → 人工审核」这一模式在整个流程中重复出现 7 次以上。将其编译为一个子图，以不同节点名称注册复用。

父图与子图之间通过**字段名匹配**传递状态：

```
父图在调用子图前设置：  system_context、task_prompt、current_draft=""、review_feedback=""、approved=False
子图运行并循环，直到：  approved=True
父图在子图返回后读取：  current_draft（最终审核通过的内容）
```

### 完整流程图

```
START
  └─► collect_user_inputs（中断：收集题材、文风、受众、调性、字数等）
        │
        ▼ 第一阶段：基础设定（顺序执行，每步 = 准备 → 审核子图 → 保存）
  prepare_core_theme     → review_core_theme     → save_core_theme
  prepare_world_building → review_world_building → save_world_building
  prepare_core_conflicts → review_core_conflicts → save_core_conflicts
  prepare_overall_outline→ review_overall_outline→ save_overall_outline
  prepare_character_profiles → review_character_profiles → save_character_profiles
        │
        ▼ 第二阶段：章节创作循环
  prepare_titles → review_titles → save_titles
  prepare_chapter → review_chapter → save_chapter ──► (current_chapter_index<5) → prepare_chapter
                                                   └─► (current_chapter_index=5) → ask_continue
                                                         ├─► 继续 → prepare_titles
                                                         └─► 结束 → END
```

### 审核子图内部流程

```
generate → llm_self_review → human_review（中断）──► 通过？ → END
                                                 └─► 有意见？ → generate（重新生成）
```

---

## 状态设计

### `ReviewSubState`（子图专用状态）

```python
@dataclass
class ReviewSubState:
    system_context: str = ""    # 基础设定内容，作为系统提示词
    task_prompt: str = ""       # 本次生成任务说明（由父图的 prepare 节点设置）
    current_draft: str = ""     # 当前正在审核的草稿
    review_feedback: str = ""   # LLM 或人工的修改意见（空 = 无问题 / 已通过）
    approved: bool = False      # True 表示人工已通过
```

### `NovelState`（主图状态）

```python
@dataclass
class NovelState:
    # ── 第零阶段：用户输入（一次性设置）─────────────────────────────────────
    genre: str = ""                  # 小说题材
    writing_style: str = ""          # 整体文风
    target_audience: str = ""        # 目标受众
    core_tone: str = ""              # 核心调性
    chapter_word_count: str = ""     # 单章字数规格
    total_word_count: str = ""       # 全书总字数规划

    # ── 与 ReviewSubState 共享的桥接字段（名称匹配传递给子图）────────────────
    system_context: str = ""
    task_prompt: str = ""
    current_draft: str = ""
    review_feedback: str = ""
    approved: bool = False

    # ── 第一阶段：基础设定结果（各步审核通过后保存）──────────────────────────
    core_theme: str = ""             # 核心立意与主线
    world_building: str = ""         # 完整世界观大框架
    core_conflicts: str = ""         # 全书顶层核心冲突
    overall_outline: str = ""        # 全书总大纲与终极结局
    character_profiles: str = ""     # 核心人物基础人设档案

    # ── 第二阶段：章节管理 ──────────────────────────────────────────────────
    current_batch_titles: list[str] = field(default_factory=list)
    all_chapter_titles: Annotated[list[str], operator.add] = field(default_factory=list)  # 累计所有章节标题，永不覆盖
    current_chapter_index: int = 0   # 当前批次中正在写第几章（0-4）；同时也是已完成章节数；=5 时触发 ask_continue
    total_chapters_written: int = 0  # 全书已完成章节总数
    continue_writing: bool = True    # 用户是否继续写下5章
```

---

## 文件结构

```
src/novel_workflow/
├── __init__.py              （保持不变）
├── state.py                 【替换】ReviewSubState + NovelState
├── graph.py                 【替换】主图完整组装
├── subgraph.py              【新建】可复用的审核子图
├── context.py               【新建】build_foundation_context() 辅助函数
├── prompts.py               【新建】各步骤的任务提示词常量
└── nodes/
    ├── __init__.py          【新建】空文件
    ├── inputs.py            【新建】collect_user_inputs 节点
    ├── foundation.py        【新建】第一阶段的 10 个 prepare_*/save_* 节点
    └── chapter.py           【新建】第二阶段的 7 个节点 + 2 个路由函数

output/                      运行时自动创建，存放章节文本文件
```

原 `nodes.py` 文件**删除**，由 `nodes/` 包替代。

---

## 各节点职责说明

### `nodes/inputs.py`

- **`collect_user_inputs`**：通过 `interrupt()` 收集 6 个基础字段。使用 `langgraph dev` 时，也可在启动线程时通过 API 直接传入这些字段。

### `nodes/foundation.py`（共 10 个节点）

每个 **`prepare_X`** 节点：
1. 调用 `build_foundation_context(state)` → 写入 `system_context`（随着设定逐步丰富）
2. 从 `prompts.py` 读取 `task_prompt`
3. 重置 `current_draft=""`、`review_feedback=""`、`approved=False`

每个 **`save_X`** 节点：
- 读取 `state.current_draft`，写入对应的固定字段（如 `core_theme = current_draft`）

**执行顺序**（按用户要求）：
```
定调性（core_theme） → 定世界（world_building） → 定冲突（core_conflicts）
  → 定主线结局（overall_outline） → 定人物（character_profiles）
```

> 注：第五步节点名称为 `prepare_character_profiles` / `review_character_profiles` / `save_character_profiles`，状态字段同名为 `character_profiles`。

### `subgraph.py`（审核子图）

| 节点 | 职责 |
|------|------|
| `generate` | 以 `system_context` 为系统提示词，调用 LLM；若 `review_feedback` 非空，则带入上稿内容和意见进行重写 |
| `llm_self_review` | 让 LLM 审查 `current_draft`；发现问题则写入 `review_feedback`，否则置空 |
| `human_review` | 调用 `interrupt()`，向人工展示草稿和 LLM 审查意见；人工输入 `approve` 或修改意见 |
| `route_after_human` | `approved=True` → END；有意见 → `"generate"`（重新生成） |

### `nodes/chapter.py`（第二阶段）

| 节点 | 职责 |
|------|------|
| `prepare_titles` | 重置 `current_draft=""`、`review_feedback=""`、`approved=False`；`task_prompt` 中附带完整的 `all_chapter_titles` 列表，供 LLM 排重 |
| `save_titles` | 按每行一个标题解析 `current_draft` 得到 5 个标题；写入 `current_batch_titles`；**return `{"all_chapter_titles": new_5_titles}` 让 reducer 自动追加**（不可手动拼接全量列表）；重置 `current_chapter_index=0` |
| `prepare_chapter` | 重置 `current_draft=""`、`review_feedback=""`、`approved=False`；读取 `current_batch_titles[current_chapter_index]`，设置对应的章节写作 `task_prompt` |
| `save_chapter` | 将 `current_draft` 写入 `./output/chapter_{num:03d}_{标题}.txt`；递增 `current_chapter_index`（+1）和 `total_chapters_written`（+1） |
| `ask_continue` | `interrupt()` → "继续写下5章？(yes/no)"，写入 `continue_writing`（bool） |
| `route_chapter_or_continue` | `current_chapter_index < 5` → `"prepare_chapter"`；否则 → `"ask_continue"` |
| `route_continue_or_end` | `continue_writing=True` → `"prepare_titles"`；否则 → END |

### `context.py`

**`build_foundation_context(state)`**：将所有已审核通过的设定字段序列化为结构化的系统提示词字符串。字段为空时跳过，因此内容会随第一阶段进展逐步丰富。

---

## 提示词策略（`prompts.py`）

每个 `prepare_X` 节点使用的 `task_prompt` 均在 `prompts.py` 中定义为常量，包括：

- `TASK_CORE_THEME`：生成核心立意与主线
- `TASK_WORLD_BUILDING`：生成世界观框架
- `TASK_CORE_CONFLICTS`：生成顶层核心冲突
- `TASK_OVERALL_OUTLINE`：生成全书大纲与终极结局
- `TASK_CHARACTER_PROFILES`：生成核心人物档案
- `TASK_CHAPTER_TITLES`：生成5章标题（含已有标题列表占位）；**要求 LLM 每行输出一个标题，不带编号、不带任何前缀**，`save_titles` 按换行符 split 后取前 5 条
- `TASK_CHAPTER_CONTENT`：生成章节正文（含章节号、标题、字数要求）

> **注**：章节 LLM 自审的系统提示词，用户后期会单独提供。当前默认审查标准为「人物关系是否有错乱」。

---

## 章节文件输出格式

```
./output/
├── chapter_001_第一章标题.txt
├── chapter_002_第二章标题.txt
└── ...
```

文件内容格式：
```
第1章 章节标题
==================================================

（章节正文内容）
```

命名规则：
- `chapter_{num:03d}` 前缀保证按字母顺序排列即为创作顺序
- 文件名中的特殊字符会被过滤处理

---

## 关键实现要点

1. **同一子图对象，多次注册**：`review_subgraph` 编译一次，以 `review_core_theme`、`review_world_building` 等不同名称注册到主图。LangGraph 1.2.4 中每个节点有独立的 checkpoint 命名空间，此模式完全支持。

2. **主图不需要显式设置 checkpointer**：`langgraph dev` 会自动注入 SQLite checkpointer，`graph = builder.compile(name="...")` 无需传入 `checkpointer=` 参数。

3. **`all_chapter_titles` 使用 `Annotated[list[str], operator.add]`**：每批 5 个标题追加到累计列表，绝不覆盖，确保全书范围内的标题排重。

4. **`langgraph.json` 无需修改**：图的导出名称 `graph` 不变，仍指向 `graph.py:graph`。

---

## 修改文件汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/novel_workflow/state.py` | 替换 | 新增 `ReviewSubState` + `NovelState` |
| `src/novel_workflow/graph.py` | 替换 | 完整图组装，注册子图和所有节点 |
| `src/novel_workflow/nodes.py` | 删除 | 由 `nodes/` 包替代 |
| `src/novel_workflow/subgraph.py` | 新建 | 可复用的审核子图 |
| `src/novel_workflow/context.py` | 新建 | 基础设定上下文构建函数 |
| `src/novel_workflow/prompts.py` | 新建 | 各步骤任务提示词常量 |
| `src/novel_workflow/nodes/__init__.py` | 新建 | 空文件 |
| `src/novel_workflow/nodes/inputs.py` | 新建 | 第零阶段节点 |
| `src/novel_workflow/nodes/foundation.py` | 新建 | 第一阶段 10 个节点 |
| `src/novel_workflow/nodes/chapter.py` | 新建 | 第二阶段 7 个节点 + 2 个路由函数 |

---

## 验证步骤

1. `langgraph dev` 启动无报错
2. 创建线程，触发 `collect_user_inputs` 中断，提供 6 个基础字段
3. `prepare_core_theme` 设置上下文 → `review_core_theme`（子图）运行 → LLM 生成 → LLM 自审 → 人工中断触发
4. 输入 `approve` → `save_core_theme` 写入 `core_theme` → 进入下一个 `prepare_world_building`
5. 5 个基础设定步骤全部完成 → 进入 `prepare_titles`，此时 `system_context` 包含完整设定
6. 生成 5 个章节标题，经审核后保存 → 开始第一章写作
7. 章节内容生成、审核、保存至 `./output/chapter_001_*.txt`
8. 5 章完成后触发 `ask_continue` 中断 → 输入 `no` → 到达 END
