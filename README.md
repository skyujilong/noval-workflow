# noval-workflow

AI 辅助小说创作工作流，基于 LangGraph 实现全程「生成 → LLM 自评 → 人工审批」闭环。从用户偏好设定到逐章输出，每个关键节点均支持多轮迭代修改。

---

## 工作流概览

```
Phase 0  用户输入（体裁、风格、受众、基调、字数要求）
   ↓
Phase 1  基础设定（5 个环节，每个均经过审稿子图）
         核心主题 → 世界观 → 核心冲突 → 整体大纲 → 人物档案
   ↓
Phase 2.5  批次小号大纲（每批开始时规划故事弧线）
   ↓
Phase 2  章节标题生成（BATCH_SIZE 个，基于弧线大纲）
   ↓
Phase 2.5  动态状态库更新（可跳过）
           用户多选要更新的字段，每字段独立审核：
           人物动态状态 / 人物关系势力 / 伏笔台账 / 阶段固化数据
   ↓
Phase 2  逐章生成（每批 BATCH_SIZE 章）
   ↓
         询问是否继续 → 继续：回到批次小号大纲（新批次）
                      → 结束：END
```

每个生成环节均经过同一个可复用审稿子图：

```
generate → llm_self_review → (有问题) → generate
                           → (通过)   → human_review → (批准) → END
                                                      → (有意见) → generate
```

---

## 详细节点流转

```
collect_user_inputs
  → prepare_core_theme → review → save
  → prepare_world_building → review → save
  → prepare_core_conflicts → review → save
  → prepare_overall_outline → review → save
  → prepare_character_profiles → review → save
  → prepare_arc_outline → review_arc_outline → save_arc_outline   ← 每批先规划弧线
  → prepare_titles → review_titles → save_titles                  ← 标题依据弧线生成
  → ask_update_tracking                                            ← 询问更新哪些状态字段
      ├─ prepare_character_status → review → save ─┐
      ├─ prepare_character_relations → review → save ┤→ route_tracking_next
      ├─ prepare_foreshadowing → review → save ──────┤
      └─ prepare_phase_summary → review → save ───────┘
  → prepare_chapter → review_chapter → save_chapter → generate_summary
  → route_chapter_or_continue
      ├─ 本批未写完 → prepare_chapter（继续写）
      └─ 本批写完  → ask_continue
                      ├─ 继续 → prepare_arc_outline（下一批重新规划）
                      └─ 结束 → END
```

---

## 特性

- **批次小号大纲**：每批章节开始时 LLM 先规划本批 N 章的故事弧线节点，经人工审核后注入 system_context，为标题生成和章节写作提供方向锚点
- **动态状态库**：4 个独立状态字段（人物状态 / 关系势力 / 伏笔台账 / 阶段固化），滑动窗口存储历史快照，每次注入最新版本；用户可按需跳过
- **多轮对话历史**：`generate` 节点保留最近 N 轮修改链（foundation/titles/arc_outline 5 轮，chapter/tracking 3 轮），LLM 能看到完整的修改演变过程
- **基础设定上下文积累**：Phase 1 已审批的内容逐步构建 system prompt，Phase 2.5 的弧线大纲与状态库快照进一步追加，后续生成始终以完整设定为基础
- **章节上下文窗口**：最近 `FULL_COUNT` 章全文 + 往前 `SUMMARY_COUNT` 章摘要，随 `NOVEL_BATCH_SIZE` 自动计算，保持叙事连贯性并控制 token 消耗
- **自动去重**：章节标题生成时自动排除已有标题
- **本地文件输出**：按小说名称隔离目录，章节正文与摘要分别保存到 `output/<小说名>/chapters/` 和 `output/<小说名>/summaries/`

---

## 安装

需要 Python 3.10+。推荐使用 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync
```

或使用 pip：

```bash
pip install -e ".[dev]"
```

---

## 配置

复制 `.env.example` 为 `.env.local` 并填写：

```env
# 必填
ARK_API_KEY=your_api_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
ARK_MODEL=doubao-seed-2.0-lite

# 批次大小：每批生成的章节数（默认 5）
NOVEL_BATCH_SIZE=5

# 可选
NOVEL_OUTPUT_DIR=./output      # 章节输出目录，默认 ./output
LANGSMITH_API_KEY=...          # LangSmith 追踪（可不填）
LANGSMITH_TRACING=true
```

`NOVEL_BATCH_SIZE` 同时控制：
- 每批生成的章节标题数量
- 提示词中的数字描述（"下 N 章"、"共 N 行"等）
- 章节上下文窗口的 `FULL_COUNT` / `SUMMARY_COUNT` 计算

---

## 运行

```bash
# 启动 LangGraph 开发服务器（带交互界面）
langgraph dev

# 或使用项目 venv
.venv/bin/langgraph dev
```

启动后在浏览器打开 LangGraph Studio，选择 `novel-writing-workflow` 图，点击运行即可开始创作流程。

---

## 项目结构

```
src/novel_workflow/
├── graph.py          # 主图组装（节点注册 + 边连接）
├── subgraph.py       # 可复用审稿子图（generate / llm_self_review / human_review）
├── state.py          # 状态定义（ReviewSubState / NovelState）
├── context.py        # 系统提示词构建（基础设定上下文、章节上下文窗口）
├── prompts.py        # 各生成节点的任务提示词与审稿提示词
├── config.py         # 全局配置常量（BATCH_SIZE / FULL_COUNT / SUMMARY_COUNT）
├── llm.py            # LLM 工厂（从环境变量读取配置）
└── nodes/
    ├── inputs.py     # Phase 0：collect_user_inputs
    ├── foundation.py # Phase 1：prepare_* / save_* 各 5 个节点
    ├── chapter.py    # Phase 2：标题生成、章节生成、摘要、循环控制
    └── arc.py        # Phase 2.5：批次大纲、动态状态库（8 个节点 + 2 个路由器）
```

输出目录（运行时自动创建，按小说名称隔离）：

```
output/
└── <小说名称>/
    ├── chapters/
    │   ├── chapter_001_标题.txt
    │   └── ...
    └── summaries/
        ├── chapter_001_标题.txt
        └── ...
```

---

## 开发

```bash
make test        # 运行测试
make test_watch  # 监听模式
make lint        # ruff 检查
make format      # ruff 格式化
```
