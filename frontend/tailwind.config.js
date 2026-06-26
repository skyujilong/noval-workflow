/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 按 Phase 分组的节点配色
        phase0: { bg: "#f3e8ff", border: "#a855f7" }, // 用户输入 - 紫
        phase1: { bg: "#dbeafe", border: "#3b82f6" }, // 基础设定 - 蓝
        phase2: { bg: "#fed7aa", border: "#f97316" }, // 章节写作 - 橙
        phase25: { bg: "#dcfce7", border: "#22c55e" }, // 弧线/状态 - 绿
        review: { bg: "#fee2e2", border: "#ef4444" }, // 审稿节点 - 红
      },
      keyframes: {
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(59,130,246,0.7)" },
          "50%": { boxShadow: "0 0 0 8px rgba(59,130,246,0)" },
        },
      },
      animation: {
        "pulse-glow": "pulseGlow 1.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
