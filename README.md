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
Phase 2  章节循环
         批量生成 5 个章节标题 → 逐章生成 → 询问是否继续
         （可循环多批）
```

每个生成环节均经过同一个可复用审稿子图：

```
generate → llm_self_review → (有问题) → generate
                           → (通过)   → human_review → (批准) → END
                                                      → (有意见) → generate
```

---

## 特性

- **多轮对话历史**：`generate` 节点保留最近 N 轮修改链（foundation/titles 5 轮，chapter 3 轮），LLM 能看到完整的修改演变过程
- **基础设定上下文积累**：Phase 1 已审批的内容逐步构建 system prompt，后续生成始终以已确定的世界观和人物为基础
- **章节上下文窗口**：最近 2 章全文 + 往前 3 章摘要，保持叙事连贯性并控制 token 消耗
- **自动去重**：章节标题生成时自动排除已有标题
- **本地文件输出**：章节正文与摘要分别保存到 `output/chapters/` 和 `output/summaries/`

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

# 可选
NOVEL_OUTPUT_DIR=./output      # 章节输出目录，默认 ./output
LANGSMITH_API_KEY=...          # LangSmith 追踪（可不填）
LANGSMITH_TRACING=true
```

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
├── prompts.py        # 各生成节点的任务提示词常量
├── llm.py            # LLM 工厂（从环境变量读取配置）
└── nodes/
    ├── inputs.py     # Phase 0：collect_user_inputs
    ├── foundation.py # Phase 1：prepare_* / save_* 各 5 个节点
    └── chapter.py    # Phase 2：标题生成、章节生成、摘要、循环控制
```

输出目录（运行时自动创建）：

```
output/
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
