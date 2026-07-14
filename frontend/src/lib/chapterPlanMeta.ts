// chapter_plan 档位色板与语义定义,ChapterPlanCards(interrupt 抽屉视图)与
// ChapterPlanReadonly(state 面板只读视图)共享同一份色系,视觉一致。
//
// bar 直接给 hex(而非 Tailwind class):动态注入(`${meta.bar}`)时 JIT 扫描
// 不稳定,曾出现类名挂上 DOM 但 CSS 规则未生成的白底白字 bug。走 inline style
// 绕开 Tailwind purge。色值取自 tailwindcss/colors 默认盘,与 chip 系一致。
//
// 与后端 state.py:ChapterPlanItem.intensity 保持一致的 7 档枚举。

export interface IntensityMeta {
  label: string;
  cls: string; // chip 用的 Tailwind class 组合(纯字面量,JIT 可扫)
  bar: string; // 时间线色块用的 hex(inline style)
  group: "lull" | "build" | "turn" | "spike";
}

export const INTENSITY_META: Record<string, IntensityMeta> = {
  铺垫: { label: "铺垫", cls: "bg-slate-100 text-slate-600 border-slate-200", bar: "#94a3b8", group: "lull" },
  缓冲: { label: "缓冲", cls: "bg-sky-50 text-sky-700 border-sky-200", bar: "#38bdf8", group: "lull" },
  回落: { label: "回落", cls: "bg-indigo-50 text-indigo-700 border-indigo-200", bar: "#818cf8", group: "lull" },
  推进: { label: "推进", cls: "bg-gray-100 text-gray-700 border-gray-300", bar: "#6b7280", group: "build" },
  小转折: { label: "小转折", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", bar: "#10b981", group: "turn" },
  大转折: { label: "大转折", cls: "bg-amber-50 text-amber-700 border-amber-300", bar: "#f59e0b", group: "spike" },
  爆发: { label: "爆发", cls: "bg-rose-50 text-rose-700 border-rose-300", bar: "#f43f5e", group: "spike" },
};

export const INTENSITY_ORDER = ["铺垫", "缓冲", "回落", "推进", "小转折", "大转折", "爆发"];
