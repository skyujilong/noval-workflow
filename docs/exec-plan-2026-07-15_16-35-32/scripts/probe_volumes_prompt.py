"""闸门 E 假设验证脚本 —— 跑 3 次 LLM 抽卷，验证输出稳定性。

用法（在项目根目录跑）：
    uv run python docs/exec-plan-2026-07-15_16-35-32/scripts/probe_volumes_prompt.py

会打印每次输出摘要、通过/失败原因，最后给出总通过率。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 让 src/novel_workflow 可导入
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

# 加载 .env.local（若装了 python-dotenv）
try:
    from dotenv import load_dotenv  # noqa: F401
    load_dotenv(_REPO_ROOT / ".env.local")
except ImportError:
    pass

from novel_workflow.llm import get_llm  # noqa: E402

# ── 提示词草稿（Step 04 落到 prompts/base.py 前的验证版）─────────────────────────
VOLUMES_PROMPT_TEMPLATE = """你是网文分卷结构化抽取助手。任务：从下面这份「整体大纲」中抽取分卷结构，返回严格 JSON 数组。

# 输入
{overall_outline}

# 硬约束
1. 输出**纯 JSON 数组**，不要 markdown 代码围栏（```），不要任何解释文字，不要前后空行。
2. 每个数组元素必须包含且仅包含 7 个字段：
   - index: int（1-based，第几卷）
   - title: str（卷名，如「第一卷 · 少年入宗」；若原文有卷名照抄，否则简短概括不超 20 字）
   - summary: str（本卷主线目标 + 情绪基调 + 收尾状态，≤80 字）
   - setup_for_next: str（卷尾要为下一卷埋的钩子/线索；最后一卷可空字符串 ""）
   - chapter_start: int（本卷起始**章号**，1-based）
   - target_min: int（本卷目标**章数**下限，例如原文"约 25 章"→ target_min=22）
   - target_max: int（本卷目标**章数**上限，例如原文"约 25 章"→ target_max=28，保守放 20%）
3. chapter_start 必须顺次拼接：第一卷 chapter_start=1；之后每卷 chapter_start = 上一卷 chapter_start + 上一卷 target_max。
4. target_min ≤ target_max，都必须 > 0；target_min/target_max 是**章数**（数量），不是章号。
5. 若原文已明确写「共 X 卷」或「第 X 卷」的分卷，严格按其分（不合并、不拆分、不重排）。
6. 若原文没有明确分卷且没写「N 卷」，默认 4 卷。

# 输出样例（仅示格式，不要照抄内容）
[
  {{"index": 1, "title": "第一卷 · 破题", "summary": "主角从平凡进入江湖，初识伙伴与敌人，卷末踏入下一阶段", "setup_for_next": "母亲身份真相埋点", "chapter_start": 1, "target_min": 22, "target_max": 28}},
  {{"index": 2, "title": "第二卷 · 内争", "summary": "主角卷入宗门斗争，母亲身份揭开", "setup_for_next": "血月教盯上主角", "chapter_start": 29, "target_min": 35, "target_max": 42}}
]

说明：卷 1 chapter_start=1，target_max=28 表示第 1-28 章占位给卷 1；卷 2 chapter_start = 1 + 28 = 29。

现在开始，直接输出 JSON 数组："""


def validate_volumes_output(text: str) -> tuple[bool, str, list | None]:
    """返回 (是否合规, 错误说明, 解析后的列表)。"""
    text = text.strip()
    # 剥掉可能的 ```json fence（LLM 有时不听话）
    if text.startswith("```"):
        lines = text.splitlines()
        # 去掉首尾 fence
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"JSON 解析失败: {e}", None

    if not isinstance(data, list) or not data:
        return False, "输出不是非空数组", None

    required = {"index", "title", "summary", "setup_for_next", "chapter_start", "target_min", "target_max"}
    next_expected_start = 1
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return False, f"第 {i+1} 项不是 dict", None
        missing = required - set(item.keys())
        if missing:
            return False, f"第 {i+1} 项缺字段: {missing}", None
        # 类型
        if not isinstance(item["chapter_start"], int) or not isinstance(item["target_min"], int) or not isinstance(item["target_max"], int):
            return False, f"第 {i+1} 项 chapter_start/target_min/target_max 不是 int", None
        # 顺次拼接：chapter_start[i] == chapter_start[i-1] + target_max[i-1]
        if item["chapter_start"] != next_expected_start:
            return False, f"第 {i+1} 项 chapter_start={item['chapter_start']} 与期望 {next_expected_start} 不符", None
        # min ≤ max
        if item["target_min"] > item["target_max"]:
            return False, f"第 {i+1} 项 target_min={item['target_min']} > target_max={item['target_max']}", None
        if item["target_min"] <= 0 or item["target_max"] <= 0:
            return False, f"第 {i+1} 项 target range 有非正数", None
        next_expected_start = item["chapter_start"] + item["target_max"]

    return True, "OK", data


def main() -> None:
    fixture_path = _REPO_ROOT / "docs/exec-plan-2026-07-15_16-35-32/fixtures/sample_overall_outline.md"
    overall_outline = fixture_path.read_text(encoding="utf-8")

    prompt = VOLUMES_PROMPT_TEMPLATE.format(overall_outline=overall_outline)

    N_RUNS = 3
    pass_count = 0
    results = []

    llm = get_llm(temperature=0.3, label="probe_volumes", max_tokens=4096, thinking="disabled")

    for i in range(1, N_RUNS + 1):
        print(f"\n═══ Run {i}/{N_RUNS} ═══", flush=True)
        try:
            resp = llm.invoke(prompt)
            text = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            print(f"✗ LLM 调用异常: {e!r}")
            results.append({"run": i, "ok": False, "err": f"LLM 异常: {e!r}", "raw": ""})
            continue

        ok, msg, data = validate_volumes_output(text)
        # 打印首 200 字用于人眼验证
        preview = (text[:400] + "…") if len(text) > 400 else text
        print(f"输出预览:\n{preview}")
        print(f"\n判定: {'✓ 通过' if ok else '✗ 失败'}: {msg}")
        if ok:
            pass_count += 1
            print(f"抽出 {len(data)} 卷: {[v['title'] for v in data]}")
        results.append({"run": i, "ok": ok, "err": msg if not ok else "", "raw": text[:1000]})

    print(f"\n\n═══ 总结 ═══")
    print(f"通过率: {pass_count}/{N_RUNS}")
    for r in results:
        marker = "✓" if r["ok"] else "✗"
        print(f"  {marker} Run {r['run']}: {r['err'] or 'OK'}")

    # 落盘
    out_path = _REPO_ROOT / "docs/exec-plan-2026-07-15_16-35-32/fixtures/probe_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")

    # 退出码：通过率 < 2/3 视为失败
    sys.exit(0 if pass_count >= 2 else 1)


if __name__ == "__main__":
    main()
