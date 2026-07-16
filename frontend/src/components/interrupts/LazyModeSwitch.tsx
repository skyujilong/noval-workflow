// 「自动模式」总开关：打开后章节循环的人工中断由前端自动应答（进入每个环节先 5s 倒计时）。
// 结构复用 ThinkingSwitch，改 amber 主题与文案。状态由上层（App）用 localStorage 持久化。

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
        className={
          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50 " +
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
      <span className="text-gray-400">{checked ? "5s 后自动应答" : "手动确认"}</span>
    </div>
  );
}
