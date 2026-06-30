// human_review / foreshadowing_review 共用的「深度思考」开关。
// 开 = 重新生成时启用深度思考（更细致但首字较慢）；关 = 秒回更省。
// 初始位置由各表单按 payload.default_thinking 决定（创作类开 / 快照类关）。

interface Props {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}

export function ThinkingSwitch({ checked, onChange, disabled }: Props) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-500">深度思考</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        disabled={disabled}
        className={
          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50 " +
          (checked ? "bg-blue-600" : "bg-gray-300")
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
        {checked ? "更细致，但首字较慢" : "秒回、更省"}
      </span>
    </div>
  );
}
