"""静态守卫:扫描 src/novel_workflow/ 全库,发现内联身份陈述即 fail。

理由:身份文本应单点定义在 render.py 的 _ROLE_TEXT 或 GenreFlavor.system_identity,
task 正文/subgraph/nodes 里再立"你是XX""# 角色:"式身份会与 L1 身份并存,构成冲突。
这条守卫兜住"新加子系统/新加节点漏走 build_system 通道直接手搓身份"的漂移。

判定策略:
- AST 遍历,精准区分字符串字面量与代码注释(注释不触发)。
- 跳过 docstring(模块/函数/类的 first-Expr Constant)——docstring 允许出现身份说明用于
  开发者阅读,不进入 LLM prompt。
- 白名单**目录前缀**:prompts/render.py(注册表单一真源)+ prompts/genres/(题材创作者身份字段
  GenreFlavor.system_identity)——只有这两个位置允许出现身份文本。

失败时给出定位 + 修正指引,让开发者能一眼知道该把新身份下沉到哪里。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# 禁止模式(在任何字符串字面量里出现即视为身份漂移):
# - "你是XX(作家/专家/工程师/...)"式:典型自造身份
# - "你的职责是/:"式:自造职责描述(往往与身份并存)
# - "# 角色:XXX"式:markdown 角色标注,常见于 review prompt 首行
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"你是[^,。\n:：]{2,40}",
    r"你的职责[是:是：]",
    r"^#\s*角色\s*[:：]",
)

# 白名单:允许出现身份文本的路径前缀(相对 src/novel_workflow/,posix 风格)
# - prompts/render.py:SystemRole 注册表 + _ROLE_TEXT 单一真源
# - prompts/genres/:各题材 GenreFlavor.system_identity 差异化字段
_WHITELIST_PREFIXES: tuple[str, ...] = (
    "prompts/render.py",
    "prompts/genres/",
)


def _collect_docstring_ids(tree: ast.AST) -> set[int]:
    """收集所有 docstring 对应的 Constant 节点 id,遍历时跳过——
    docstring 是给开发者看的,不进入 LLM 上下文,不算身份漂移。
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _scan_file(py_file: Path, rel: str) -> list[str]:
    """扫描单文件,返回违规位置列表(每项形如 'rel:line: excerpt')。"""
    source = py_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # 有语法错的文件让 pytest 别的测试去暴露,这里跳过不产生假阳性
        return []
    docstring_ids = _collect_docstring_ids(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstring_ids:
            continue
        for pat in _FORBIDDEN_PATTERNS:
            if re.search(pat, node.value, re.MULTILINE):
                excerpt = node.value.replace("\n", " ")[:80]
                hits.append(f"{rel}:{node.lineno}: {excerpt!r}")
                break
    return hits


def test_no_inline_identity_in_prompts() -> None:
    """守卫:src/novel_workflow/ 全库不得有内联身份陈述(白名单外)。"""
    root = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "novel_workflow"
    )
    assert root.exists(), f"源码根目录不存在:{root}"

    hits: list[str] = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root).as_posix()
        if any(rel.startswith(w) for w in _WHITELIST_PREFIXES):
            continue
        hits.extend(_scan_file(py_file, rel))

    assert not hits, (
        "以下位置内联了身份陈述,应下沉到 render.py 的 SystemRole 注册表:\n"
        + "\n".join(hits)
        + "\n\n修正指引:\n"
        + "- 若属题材创作者身份 → 写到 prompts/genres/<flavor>.py 的 "
        "GenreFlavor(system_identity=...) 字段;\n"
        + "- 其他身份 → 在 prompts/render.py 新增 SystemRole 枚举项 + _ROLE_TEXT 表项,"
        "调用点走 build_system(role=SystemRole.XXX, ...);\n"
        + "- 若确实是 docstring/注释文案(不进 prompt),把它写成模块/函数/类的 docstring "
        "(AST 首个 Expr Constant),守卫会自动跳过。"
    )
