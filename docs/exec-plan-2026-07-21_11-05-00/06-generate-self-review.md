# 06-generate-self-review

## Goal
改 subgraph.generate / llm_self_review 走 render_user，只一套 render 逻辑，解决自审丢资料。无条件分支。此时 03-05 所有 prepare 已产出三字段。

## Depends on
- 01(render_user)、02(schema)、03-05(所有 prepare 已产三字段) 完成

## Do
1. subgraph.py generate（:226-303）：
   - 删 is_snapshot 分支拼"数据维护员"system（身份已在 prepare 的 L1）
   - 非 snapshot 首轮：messages=[SystemMessage(state.system_prompt), HumanMessage(render_user(state.context_prompt, state.task_prompt))]
   - snapshot 首轮：同上（prepare 已把数据维护员身份进 system_prompt，exclude_snapshots 的设定进 context_prompt）。**确认 generate 不再内联拼身份/设定**
   - 重放分支：历史轮次 replay（历史 user 无 L2 可恢复，接受）；最新轮 messages.append(HumanMessage(render_user(state.context_prompt, regen_instruction)))
   - evolved_directives 注入（:275-279）：打回重跑分支仍从 overrides 新鲜读三桶拼 regen_instruction 末尾，不动
2. subgraph.py llm_self_review（:309-390）：
   - 删 is_snapshot 分支拼"数据审核员"system（身份进 L1）
   - 非 snapshot：system=SystemMessage(state.system_prompt) + user=render_user(state.context_prompt, review_prompt)（**解决自审丢资料！**L2 与 review_prompt 同在 user）
   - snapshot：同上模式（审核员身份进 system_prompt；task_prompt 含 prev 基线仍前置，见 :367）
   - 删内联 system_content 拼装（:249-254, :369-374）
3. _SNAPSHOT_REVIEW_TYPES 仍用于 thinking 决策（:231, :306），不动
4. 验收脚本加 generate/自审拼装检查（mock state 跑 generate 不调 LLM？generate 调 llm.invoke 需 mock。或单独测 render_user 拼装正确性）

## Verify
1. ruff format+check subgraph.py
2. 验收脚本：模拟 generate 首轮/重放/自审的 messages 拼装（mock LLM 或抽 render 逻辑单测）
3. 重点：自审的 user 含【参考资料】L2（解决丢资料）；generate 只一套 render 无分支
4. test_review_subgraph_human_feedback.py / test_snapshot_worldview_injection.py 适配新字段（system_context -> system_prompt/context_prompt）

## Notes
- 执行结果：✅ 完成
- 改动文件：
  - subgraph.py：generate 删 is_snapshot 的 system 内联拼装，统一 SystemMessage(state.system_prompt) + render_user(state.context_prompt, task)；llm_self_review 同样走 render_user（**解决自审丢资料核心**：review_prompt 与 L2 同在 user）；render_user import 提顶
  - 5 测试文件适配新字段：test_review_subgraph_human_feedback / test_snapshot_worldview_injection / test_scene_beats / test_evolution / test_edit_step_state_schema
- 关键设计：
  - generate 无条件分支（删 is_snapshot system 拼装），只一套 render 逻辑；is_snapshot 仅用于 thinking 决策
  - 重放分支最新轮用 render_user(context_prompt, regen) 拼装，让重写也能看到 L2
  - llm_self_review: system=state.system_prompt + user=render_user(state.context_prompt, review_prompt) -> 自审能看到设定，跨设定一致性审核恢复
- 验证：ruff 全过 / 6 核心测试 65 passed / 验收脚本 85 PASS 0 FAIL
- 标志性断言：test_snapshot_generate_injects_worldview 现断言"WORLD 在 user 不在 system"--验证资料从 system 移 L2/user 成功，system 瘦下来
- 预期红：edit_step_subgraph/chapter_plan_edit_subgraph 仍引用 system_context（07 修）；全量 pytest 这两模块相关会红

