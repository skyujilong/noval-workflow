// 「自动模式」总开关：打开后章节循环的人工中断由前端自动应答（进入每个环节先 5s 倒计时）。
// 结构复用 ThinkingSwitch，改 amber 主题与文案。状态由上层（App）用 localStorage 持久化。
// disabled=true（非写作阶段）时禁止开启，并把尾部文案改为提示语。

interface Props {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}

export function LazyModeSwitch({ checked, onChange, disabled }: Props) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-500">自动模式</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        disabled={disabled}
        title={disabled ? "仅进入章节写作阶段后可用" : undefined}
        className={
          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
          (checked && !disabled ? "bg-amber-500" : "bg-gray-300")
        }
      >
        <span
          className={
            "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform " +
            (checked ? "translate-x-4" : "translate-x-0.5")
          }
        />
      </button>
      <span className="text-gray-400">
        {disabled ? "仅写作阶段可用" : checked ? "5s 后自动应答" : "手动确认"}
      </span>
    </div>
  );
}

interface LongPlanProps {
  checked: boolean;
  onChange: (next: boolean) => void;
}

/**
 * 「长线规划自动化」子开关：仅在自动模式开启且处于写作阶段时展示。
 * 关（默认）= 自动模式遇长线章节规划点会停下交回人工，防剧情长期偏移；
 * 开 = 长线规划也一路自动跑（用户自担偏移风险）。
 */
export function LongPlanAutoSwitch({ checked, onChange }: LongPlanProps) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-500">长线规划</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        title="关：自动模式遇长线章节规划会停下交回人工（防剧情偏移）；开：长线也一路自动跑"
        className={
          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors " +
          (checked ? "bg-amber-500" : "bg-gray-300")
        }
      >
        <span
          className={
            "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform " +
            (checked ? "translate-x-4" : "translate-x-0.5")
          }
        />
      </button>
      <span className="text-gray-400">{checked ? "长线也自动" : "停在长线规划"}</span>
    </div>
  );
}
