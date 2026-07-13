# 02-contracts-frontend

## Goal
镜像 step 01 的后端契约到前端：`interruptTypes.ts` 加 3 个枚举值、TYPE_TO_FORM 映射、DIRECTION_TITLE 兜底登记；`types.ts` 加中文 REVIEW_TYPE_LABELS。

## Depends on
- 01-contracts-backend（字符串值必须一字不差）

## Do
1. `frontend/src/lib/interruptTypes.ts`：
   - 在第 50 行 `SCENE_BEATS_REVIEW: "scene_beats_review",` 之后追加：
     ```
     // 章级角色档案发现（每章正文完成后自动）
     CHARACTER_PROFILES_DISCOVER_ENTRY_GATE: "character_profiles_discover_entry_gate",
     CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT: "character_profiles_discover_direction_input",
     CHARACTER_PROFILES_DISCOVER_REVIEW: "character_profiles_discover_review",
     ```
   - 在 `TYPE_TO_FORM`（第 251-298 行）里对应位置追加三行：
     ```
     [InterruptType.CHARACTER_PROFILES_DISCOVER_ENTRY_GATE]: "entry_gate",
     [InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT]: "direction",
     [InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW]: "human_review",
     ```
   - 在 `DIRECTION_TITLE`（第 320-327 行）里追加：
     ```
     [InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT]: "角色档案发现调整方向",
     ```
2. `frontend/src/lib/types.ts`：
   - 在 `REVIEW_TYPE_LABELS`（第 118-135 行）`scene_beats: "章节 scene beats",` 之后追加：
     ```
     character_profiles_discover: "角色档案发现",
     ```
   - `EVOLVABLE_REVIEW_TYPES`（第 145 行）**不改**。

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover/frontend && npx tsc --noEmit`（前端类型检查通过——`TYPE_TO_FORM` 的 `Record<InterruptTypeValue, FormKind>` 要求所有 InterruptTypeValue 都要有映射，如果遗漏会立即报错）。

## Notes
- Changed: `frontend/src/lib/interruptTypes.ts`（+3 枚举值 / +3 TYPE_TO_FORM / +1 DIRECTION_TITLE）；`frontend/src/lib/types.ts`（+1 REVIEW_TYPE_LABELS）
- Verify: `npx tsc --noEmit` OK（静默通过，Record 全覆盖硬约束无违反）
