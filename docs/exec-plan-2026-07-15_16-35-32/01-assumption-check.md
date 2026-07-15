# 01-assumption-check

## Goal
闸门 E：在动手改代码前，先验证一个核心假设——**LLM 能从 `overall_outline`（markdown 自由文本）稳定抽出合规的卷 JSON 数组**（含 index/title/summary/setup_for_next/chapter_start/target_min/target_max 7 字段），且 chapter_start 顺次拼接、target_min ≤ target_max。

不通过则重设方案（可能需要脑爆环节先结构化产出卷信息，而不是事后从 overall_outline 抽）。

## Depends on
- 无

## Do
1. 从代码里找一份现成的 `overall_outline` 样本作为测试输入。首选：
   - `tests/` 或 `docs/` 目录下已有的示例（`rg -l "第一卷|第二卷" src/ tests/ docs/`）
   - 若无，直接手写一份典型玄幻小说 4 卷大纲作为验证输入（放入 `docs/exec-plan-2026-07-15_16-35-32/fixtures/sample_overall_outline.md`）
2. 起草 `prepare_volumes` 的 prompt 草稿（不落到 `prompts/base.py`，写到 mini-plan 的 Notes 里）。关键约束：
   - 输入：`{overall_outline}`（整段 markdown）
   - 输出：**纯 JSON 数组**，无 markdown fence，无解释文字
   - 每项字段：`index / title / summary / setup_for_next / chapter_start / target_min / target_max`
   - 硬约束：`chapter_start[0] = 1`；`chapter_start[i] = target_max[i-1] + 1`；`target_min ≤ target_max`；最后一卷 `setup_for_next` 可为空
   - 如 overall_outline 已明写"共 N 卷/第 X 卷"，严格按其分；否则默认 4 卷
3. 手工调用 LLM（可用项目现有 CLI/脚本，或简单 python 脚本走 `langchain_anthropic` / `langchain_openai` — 参考 `src/novel_workflow/llms.py` 中的模型工厂）跑 3 次生成，对比：
   - 输出是否稳定合规（3 次都能解析成 JSON 数组 + 字段完整）
   - `chapter_start` 是否顺次拼接
   - `target_min ≤ target_max` 是否成立
4. 记录失败模式（若有）：出错原因？加什么强约束能修好？

## Verify
1. `python3 docs/exec-plan-2026-07-15_16-35-32/scripts/probe_volumes_prompt.py` （若写成脚本）或人工跑 3 次 LLM 生成
2. 3 次输出中至少 2 次能通过：
   - `json.loads(output)` 不抛
   - 是 list，每项含 7 个必需字段
   - `chapter_start` 顺次拼接
   - `target_min ≤ target_max`
3. 若通过率 < 2/3：分析失败根因，调整 prompt 后重试；仍不通过则**停下汇报，方案可能需要改为"脑爆环节主动结构化产出卷"**

## Notes
- 记录 prompt 草稿终版
- 记录 3 次 LLM 输出片段（可截断，只留关键部分）
- 记录通过率与失败模式
- 若通过：把 prompt 草稿传递给 Step 04 落到 `prompts/base.py`

## 执行结果（2026-07-15）

**首轮 3/3 失败**：LLM 三次都把 `target_max` 理解为"本卷章数"而非"绝对章号"，导致 `chapter_start[i+1] = target_max[i] + 1` 校验全挂。这不是 LLM 稳定性问题，是**我的字段语义与作者/LLM 直觉不一致**——作者说"卷 2 约 40 章"想的就是章数，不是"卷 2 结束在第 X 章"。

**语义修正**（关键决策，需传递到下游步骤）：
- `target_min / target_max` = **本卷章数**（数量），不是绝对章号
- 拼接公式：`chapter_start[i+1] = chapter_start[i] + target_max[i]`（前卷按上限占位）
- Step 02 的 Volume dataclass 注释必须体现此语义
- Step 03 的 `find_boundary_crossings` 内部需把 `(chapter_start, target_min, target_max)` 转成绝对章号窗口 `[chapter_start + target_min - 1, chapter_start + target_max - 1]` 再判穿越
- Step 04 的 `volumes_prompt` 沿用本步 fixtures/scripts 中已验证的 prompt 模板

**修正后 3/3 通过**：
- Run 1: 卷 1 [1, 22-28] / 卷 2 [29, 35-42] / 卷 3 [71, 40-50] / 卷 4 [121, 40-50]
- Run 2: 卷 1 [1, 20-30] / 卷 2 [31, 32-48] / 卷 3 [79, 40-50] / 卷 4 [129, 42-52]
- Run 3: 卷 1 [1, 22-28] / 卷 2 [29, 35-45] / 卷 3 [74, 40-50] / 卷 4 [124, 42-52]

**产物**：
- `fixtures/sample_overall_outline.md` — 四卷 300 万字玄幻大纲样本
- `fixtures/probe_results.json` — 3 次跑的原始输出（用于回归对比）
- `scripts/probe_volumes_prompt.py` — 可复用的 probe 脚本 + 校验器（Step 04 单测可复用同一份校验逻辑）
- **prompt 模板终版**：见 `scripts/probe_volumes_prompt.py` 中的 `VOLUMES_PROMPT_TEMPLATE`

**结论**：假设成立，可以进入 Step 02。LLM `temperature=0.3` + `thinking="disabled"` 下 3/3 稳定通过，5-11s/次，374 tok output 上限充分。
