# 07-frontend-types

## Goal
把 Volume 类型加进前端契约层：`types.ts` 加 `Volume` interface + `NovelState.volumes` + `REVIEW_TYPE_LABELS.volumes` 标签；`interruptTypes.ts` 加 `VOLUME_BOUNDARY_GATE` 枚举 + 表单映射（先给字符串占位，Step 08 补组件）。

## Depends on
- 02-schema-and-contracts（后端 Volume dataclass / VOLUME_BOUNDARY_GATE 枚举字符串已定案）
- 06-graph-and-prompt-injection（后端已上线，前端类型对齐）

## Do
1. `frontend/src/lib/types.ts`：
   - 加 `Volume` interface：字段与后端 dataclass 完全对齐（index/title/summary/setup_for_next/chapter_start/target_min/target_max/actual_end/status），`actual_end: number | null`，`status: "planning" | "in_progress" | "closed"`
   - `NovelState`（或对应 state 类型）加 `volumes: Volume[]` 字段
   - `REVIEW_TYPE_LABELS` 表加 `volumes: "分卷规划"`
2. `frontend/src/lib/interruptTypes.ts`：
   - `InterruptType` 常量对象加 `VOLUME_BOUNDARY_GATE: "volume_boundary_gate"`
   - `TYPE_TO_FORM` 映射先加 `[InterruptType.VOLUME_BOUNDARY_GATE]: "VolumeBoundaryGateForm"`（Step 08 会实现组件；此时是"未实现"占位，`InterruptHandler` 走 fallback 或 raise 都可接受）

## Verify
1. `cd frontend && pnpm tsc --noEmit` → 无类型错误
2. `cd frontend && pnpm lint` 或 `pnpm build` 通过

## Notes
- 前端 volumes 字段名与后端契约 100% 对齐；LangGraph state 序列化会把 dataclass 转 dict，前端拿到就是 `Volume` 形状
- Step 08 才落地 3 个组件（VolumeRibbon / VolumesReviewForm / VolumeBoundaryGateForm），本步只补契约

### 执行结果 (2026-07-15)

**`frontend/src/lib/types.ts`** (修改):
- 新增 `Volume` interface（与后端 dataclass 逐字段对齐，含 status 联合类型）
- `NovelState` 加 `volumes: Volume[]` 字段
- `EMPTY_NOVEL_STATE` 加 `volumes: []` 初始化
- `REVIEW_TYPE_LABELS` 加 `volumes: "分卷规划"`

**`frontend/src/lib/interruptTypes.ts`** (修改):
- `InterruptType` 常量对象加 `VOLUME_BOUNDARY_GATE: "volume_boundary_gate"`
- `FormKind` 联合类型加 `"volume_boundary_gate"`
- `TYPE_TO_FORM` 映射加 `[VOLUME_BOUNDARY_GATE]: "volume_boundary_gate"`
- 新增结构化 payload：`VolumeBoundaryCrossing` / `VolumeDictSnapshot` / `VolumeBoundaryOption` / `VolumeBoundaryGatePayload`
- 新增 3 个 resume 类型 + 3 个 builder：`buildVolumeContinueResume` / `buildVolumeCloseAtResume` / `buildVolumeExtendResume`

### 验证
- `pnpm tsc --noEmit` → EXIT=0（类型检查通过）
- `pnpm build` → EXIT=0（`✓ built in 2.08s`）
- 无 lint 命令（项目未配置），build 涵盖所有 tsc 检查
