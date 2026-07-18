"""题材注册表与提示词包工厂。

get_prompt_pack(genre) 按 state.genre 加载对应题材的 PromptPack；未命中时回退到
"通用"包（不报错、不阻断流程）。提示词包对象不入 langgraph state。
"""

from __future__ import annotations

from noval_workflow.prompts.base import GenreFlavor, PromptPack
from noval_workflow.prompts.genres import (
    apocalypse,
    comedy_isekai,
    generic,
    romance,
    sci_fi,
    urban,
    xianxia,
)

# 题材注册表：genre_key → GenreFlavor。
# 同一题材包可注册多个别名（如"玄幻"/"仙侠"共用 xianxia.FLAVOR）。
_REGISTRY: dict[str, GenreFlavor] = {
    "通用": generic.FLAVOR,
    "末日求生": apocalypse.FLAVOR,
    "灾变": apocalypse.FLAVOR,
    "玄幻": xianxia.FLAVOR,
    "仙侠": xianxia.FLAVOR,
    "都市": urban.FLAVOR,
    "科幻": sci_fi.FLAVOR,
    "两性情感": romance.FLAVOR,
    "搞笑异世界": comedy_isekai.FLAVOR,
}

# 回退用的通用包 key
_DEFAULT_KEY = "通用"


def get_prompt_pack(genre: str, novel_name: str = "") -> PromptPack:
    """按题材获取提示词包。

    精确匹配注册表；未命中时回退到通用包。返回的 PromptPack.genre 保留传入的
    genre 原值（便于排查），但 flavor 使用实际命中的题材包。

    当传入 novel_name 时，读取该小说的 prompt_overrides.json 并把覆盖项合并进 flavor
    （局部覆盖，留空字段回退题材默认）。覆盖项不入 langgraph state，每次调用新鲜读取，
    故编辑后即时生效、对历史回放也生效。novel_name 默认为空时保持原行为（向后兼容）。
    """
    flavor = _REGISTRY.get(genre or "", _REGISTRY[_DEFAULT_KEY])
    if novel_name:
        # 惰性 import：overrides -> context -> prompts.__init__ -> registry 会成环
        from noval_workflow.prompts.overrides import apply_overrides, load_overrides

        flavor = apply_overrides(flavor, load_overrides(novel_name))
    return PromptPack(genre, flavor)


def available_genres() -> list[str]:
    """返回前端下拉可用的题材主键列表（不含别名，顺序固定）。"""
    return ["通用", "末日求生", "玄幻", "都市", "科幻", "两性情感", "搞笑异世界"]
