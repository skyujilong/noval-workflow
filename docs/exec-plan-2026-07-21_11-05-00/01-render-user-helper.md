# 01-render-user-helper

## Goal
扩展 render.py：加 `render_user(context, task)` 供 generate/llm_self_review 复用拼 user；`build_system` 支持非创作身份（snapshot 的"数据维护员"）。为后续 prepare/generate 统一组装提供单一拼装源，避免两处漂移。

## Depends on
- P0 已建的 render.py（PromptRequest/render/build_system/HARD_CONTRACTS/ContextSection）

## Do
1. render.py 加 `render_user(context: str, task: str) -> str`：
   - context 非空 -> `f"【参考资料】\n{context}\n\n【本次任务】\n{task}"`
   - context 空 -> 纯 task（向后兼容场景：generate 重放历史轮次 task_prompt 无 L2）
   - 与 render() 的 user 拼装同源：render() 内部调 render_user，消除重复。
2. render() 重构：内部调 render_user，逻辑同源。
3. build_system 扩展：identity 参数已是 str，snapshot 传"你是严谨的小说数据维护员…"即可，无需改签名。但补一个常量 `SNAPSHOT_IDENTITY_MAINTAINER` / `SNAPSHOT_IDENTITY_REVIEWER`（数据维护员/审核员身份文案），供 prepare/generate 复用，避免内联散落。
4. 更新 core_theme_request 适配 render() 重构（内部调 render_user）。

## Verify
1. `ruff check src/novel_workflow/prompts/render.py` 通过
2. `mypy --strict src/novel_workflow/prompts/render.py` 通过
3. `python -m pytest tests/unit_tests/test_prompt_render.py -q` 6 passed（含 render_user 新测）
4. 新增 test：render_user 空 context 退化为纯 task；非空含【参考资料】/【本次任务】分区
5. `python scripts/verify_prompt_arch.py` 仍全 PASS（render 重构后 P0 验收不回归）

## Notes
- 执行结果：✅ 完成
- 改动文件：src/novel_workflow/prompts/render.py（加 render_user + 重构 render 调它 + 加 SNAPSHOT_IDENTITY_MAINTAINER/REVIEWER 常量）、tests/unit_tests/test_prompt_render.py（加 5 个新测）
- 验证：ruff format+check 通过 / pytest 11 passed（原 6 + 新 5）/ P0 验收脚本 8 项全 PASS（render 重构无回归）/ render_user 与 render 同源已断言
- 关键：render() 现内部调 render_user，两者拼装同源；generate/llm_self_review 后续调 render_user 拼用户消息解决自审丢资料

