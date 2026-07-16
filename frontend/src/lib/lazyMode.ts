// 「自动模式」自动应答决策：把某个 interrupt 的 payload 映射成「该自动发什么 resume 值」。
// 纯函数，无副作用，复用 interruptTypes.ts 的权威 type→FormKind 分发与 resume 值 builder。
//
// 产品决策（用户拍板）：闸门全部执行、批末自动继续、勾选/确认类自动采纳 AI 建议。
// 故这里除黑名单外，章节循环内的每类中断都给一个「继续往前走」的默认值。

import {
  InterruptType,
  EXECUTE_VALUE,
  SKIP_VALUE,
  buildReviewResume,
  buildVolumeContinueResume,
  formKindFromType,
  type HumanReviewPayload,
  type EntitySelectConfirmPayload,
  type ForeshadowPruneConfirmPayload,
  type EntityCardsPruneConfirmPayload,
} from "./interruptTypes";

/** 自动模式对单个 interrupt 的处置：auto=false / null 表示不自动、维持手动表单。 */
export interface LazyResume {
  auto: boolean; // 是否参与自动应答
  value: unknown; // 传给 resume() 的确切值
  actionLabel: string; // 倒计时 banner 显示的动作名
}

/**
 * 强制手动的 type 黑名单（冗余护栏）：即便将来 FormKind 映射改动也不会被自动化。
 * 语义——初始参数采集、Phase1 设定一致性冻结（破坏性、不在章节循环）、脑爆阶段。
 * 注：这些 type 在 getLazyResume 的 switch 里本就落到 default→null，此处是双保险。
 */
export const LAZY_DENY = new Set<string>([
  InterruptType.USER_INPUTS,
  InterruptType.USER_INPUTS_ERROR,
  InterruptType.CONSISTENCY_GATE,
  InterruptType.CONSISTENCY_DIFF,
  InterruptType.BRAINSTORM_GATE,
  InterruptType.BRAINSTORM_CHAT,
  InterruptType.BRAINSTORM_FINALIZE_CONFIRM,
  InterruptType.BRAINSTORM_EXTRACT_REVIEW,
  InterruptType.BRAINSTORM_CORE_THEME_CONFIRM,
  InterruptType.BRAINSTORM_WORLD_BUILDING_CONFIRM,
  InterruptType.BRAINSTORM_POWER_SYSTEM_CONFIRM,
  InterruptType.BRAINSTORM_CORE_CONFLICTS_CONFIRM,
]);

/**
 * 破坏性精简 type：自动应答会真删库（伏笔/实体卡），不可逆。
 * 单列出来便于日后想改成「保守」（留手动或更长倒计时）时集中调整。
 */
export const DESTRUCTIVE_TYPES = new Set<string>([
  InterruptType.FORESHADOW_PRUNE_CONFIRM,
  InterruptType.ENTITY_CARDS_PRUNE_CONFIRM,
]);

/**
 * 计算某个 interrupt payload 在自动模式下的自动 resume 处置。
 * @returns LazyResume（auto=true 才自动）；黑名单/未覆盖类型返回 null（维持手动）。
 */
export function getLazyResume(payload: unknown): LazyResume | null {
  if (!payload || typeof payload !== "object") return null;
  const type = (payload as { type?: unknown }).type;
  if (typeof type !== "string") return null;

  // 黑名单短路：破坏性冻结 / 初始参数 / 脑爆一律手动
  if (LAZY_DENY.has(type)) return null;

  const kind = formKindFromType(type);
  switch (kind) {
    // 闸门类：全部执行（发非跳过词 "yes"）
    // 覆盖所有 *_entry_gate + foreshadow_prune_ask + entity_cards_prune_ask
    case "entry_gate":
      return { auto: true, value: EXECUTE_VALUE, actionLabel: "自动执行本环节" };

    // 审核类：自动通过（空 feedback），thinking 复用 payload.default_thinking 默认规则
    case "human_review":
    case "foreshadowing_review": {
      const p = payload as HumanReviewPayload;
      const thinkingOn = p.default_thinking !== "disabled";
      return {
        auto: true,
        value: buildReviewResume("", thinkingOn),
        actionLabel: "自动通过审核",
      };
    }

    // 批末是否继续：自动继续（空串 ∈ 后端 _CONTINUE_SIGNALS）
    case "ask_continue":
      return { auto: true, value: "", actionLabel: "自动继续下一批" };

    // 分卷边界：默认继续本卷（最不激进的一支）
    case "volume_boundary_gate":
      return {
        auto: true,
        value: buildVolumeContinueResume(),
        actionLabel: "自动继续本卷",
      };

    // 章末实体入库筛选：全部入库（发 new_cards + updates 的全部 key）
    case "entity_select_confirm": {
      const p = payload as EntitySelectConfirmPayload;
      const allKeys = [
        ...p.new_cards.map((c) => c.key),
        ...p.updates.map((u) => u.key),
      ];
      return {
        auto: true,
        value: JSON.stringify(allKeys),
        actionLabel: "自动全部入库",
      };
    }

    // 伏笔精简：采纳 AI 建议，删除全部 to_delete（发其 id 数组）
    case "foreshadow_prune_confirm": {
      const p = payload as ForeshadowPruneConfirmPayload;
      const ids = (p.to_delete ?? []).map((d) => d.id);
      return {
        auto: true,
        value: JSON.stringify(ids),
        actionLabel: `自动采纳AI精简伏笔（删 ${ids.length} 项）`,
      };
    }

    // 卡库精简：采纳 AI 建议，删除 suggested=true 的卡（发其 name 数组）
    case "entity_cards_prune_confirm": {
      const p = payload as EntityCardsPruneConfirmPayload;
      const names = (p.cards ?? []).filter((c) => c.suggested).map((c) => c.name);
      return {
        auto: true,
        value: JSON.stringify(names),
        actionLabel: `自动采纳AI精简卡库（删 ${names.length} 张）`,
      };
    }

    // AI 结果确认：接受 AI 版本（空串）
    case "arc_confirm":
    case "arc_titles_confirm":
    case "chapter_plan_edit_confirm":
      return { auto: true, value: "", actionLabel: "自动接受AI结果" };

    // 方向输入：自动模式无法代答创意，发空串（=用默认继续/不注入人工方向，步骤照跑）
    case "direction":
    case "arc_direction":
    case "chapter_plan_edit_direction":
      return { auto: true, value: SKIP_VALUE, actionLabel: "自动用默认方向继续" };

    // 其余（brainstorm_* / user_inputs / consistency_* / unknown）维持手动
    default:
      return null;
  }
}
