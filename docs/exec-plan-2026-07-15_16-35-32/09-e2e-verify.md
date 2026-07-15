# 09-e2e-verify

## Goal
后端 + 前端完成后，手工走一遍完整流程验收场景 A-D。此步不写代码，只做端到端验收和记录问题。

## Depends on
- 01-08 全部完成

## Do & Verify（场景 A-D）

### 场景 A：新建小说走到分卷 review
1. `make dev` 启动前后端
2. 新建小说 → 走脑爆 → 基础设定 → overall_outline 生成通过（4 卷式）
3. **应观察**：进入 `VolumesReviewForm`，LLM 抽出 4 卷（title/summary/setup_for_next/target_min/target_max），用户编辑后提交
4. **应观察**：顶部 `VolumeRibbon` 出现 4 卷横条，第一卷高亮 `in_progress`，其余 `planning`

### 场景 B：第一次 chapter_plan 触发 gate
1. 继续生成人物档案 → 一致性总审通过 → save_config 后走到第一次 `prepare_chapter_plan`
2. 假设 `total_chapters_written=0`, `CHAPTER_PLAN_WINDOW=40`, 第一卷 `target_min=22 target_max=28`
3. **应观察**：`window=[1,40]` 穿越卷一 `target_min=22, target_max=28` → `VolumeBoundaryGateForm` 弹出
4. 用户选"继续本卷" → chapter_plan 生成，40 条条目里 26-40 章的 purpose 应体现"卷二铺垫" 语义（LLM 拿到了卷位置卡）
5. **应观察**：生成完的 chapter_plan 里，第 25 章附近的 `ending_hook` 应含卷一 `setup_for_next` 元素

### 场景 C：卷边界调整回改
1. 写到卷一 target_max 附近时（触发下次 chapter_plan gate），选"在第 25 章收卷"
2. **应观察**：`state.volumes[0].actual_end=25, status="closed"`；`state.volumes[1].chapter_start=26, status="in_progress"`
3. 下一次 `arc_outline` 位置卡应显示"当前所在：第 2 卷 · 第 26 章起"
4. 顶部横条：卷一变 ✓ 显示 `1-25`，卷二变高亮

### 场景 D：arc_outline 拿到卷位置
1. 通过后端日志或 langgraph state 观察（也可用 chrome-devtools 拦 network）
2. **应观察**：`arc_outline` 的 task_prompt 头部含【当前卷位置】段

## Notes
- 端到端跑通即算 Step 09 通过；发现问题回退到具体 step 修
- LLM 生成有随机性，如观察不到"卷二铺垫"语义可多跑 2-3 次；若始终不含则回 Step 06 检查 prompt 注入
- 若发现前端 payload 字段名不匹配 → 回 Step 07-08 对齐
