"""章级「角色档案发现」提示词与组装函数。

每章正文完成后（save_chapter → generate_summary 之后）自动触发：LLM 读本章正文 +
已有 character_profiles → 输出**合流后的完整档案 markdown** → 覆盖写回 state.character_profiles。

与 Phase 1 初版档案生成（prompts/base.py::PromptPack.character_profiles_prompt）的
边界：Phase 1 一次成型出全主要角色的双层人设/成长弧光/能力底牌契约；本模块是
Phase 2 阶段的「补录/续写」，只做增量——**只追加**新角色或已有角色的本章新暴露信息，
禁止改写既定人设。审核 prompt 也是**宽松版**（不检查卡司配额/双层人设/能力底牌/
力量体系归属），因为次要新角色允许留白，硬套 Phase 1 硬清单会一直被打回。

字段类型不变（state.character_profiles: str），LLM 全量输出合流后完整档案，save 端
直接覆盖写回——不做 delta 合并算法（str 字段无结构 anchor，代码合流反而更脆）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


# ── 生成提示词 ────────────────────────────────────────────────────────────────

CHARACTER_PROFILES_DISCOVER_PROMPT = """请根据本章正文，对人物档案做「发现式」增量补录，输出**合流后的完整档案 markdown**。

【本章号】第 {chapter_num} 章

【已有人物档案】
{existing_profiles}

【本章正文】
{chapter_draft}

---

## 任务

对照【已有人物档案】和【本章正文】，识别两类信息并补录到档案里：

1. **新登场角色**：本章正文中出现、但未在已有档案里登记的角色（有名有姓、有戏份、非路人 NPC）
2. **已有角色的新暴露信息**：本章正文中已知角色暴露出的新能力/新关系/新动机/新处境（首次亮相的能力、首次揭示的身份、首次表明的立场等）

## 输出契约（必须严格遵守）

**输出形态**：整块 markdown 文本，将直接**覆盖替换** state.character_profiles 字段——这是人物档案，**不是章节正文**，不要输出正文情节。

**保真硬约束**（最重要）：
- **必须保留【已有人物档案】中所有原有角色条目原样**——禁止裁剪、总结、压缩、重写任何已有条目的措辞。
- 只允许**追加**：在文末追加新角色条目；或在原有角色条目的末尾追加「【第 {chapter_num} 章新增】…」补充段。
- 已有角色的既定人设（性格底色、立场归属、能力上限、成长天花板）**禁止改写**，只能追加"本章暴露的新信息"。

**反幻觉硬约束**：
- 不得凭空虚构本章未提及的角色。
- 不得把 NPC/背景群众/一句台词的过路人写成正式档案条目——只登记有明确姓名+有实质戏份的新角色。
- 已有角色的"新信息"必须来自本章正文的显式描写，不允许推测/演绎。

**格式约束**：
- 新增角色的档案条目允许比 Phase 1 初版**简洁**（3-5 行即可）——不要求写双层人设、力量体系归属、四卷成长弧光、能力底牌契约等 Phase 1 硬清单。次要新角色只需：姓名 + 身份/关系 + 本章戏份摘要 + （若有）能力/动机线索。
- 新增段插入位置要合理：新主要角色靠近同类主角/配角段；反派靠近反派段；次要角色/NPC 可独立"本章新增"小节挂在文末。
- 直接输出 markdown 文本，不要包 code fence，不要有"以下是修改后的档案："这类元叙述。

**空发现允许**：
- 若本章既无新登场角色、已知角色也无新暴露信息（如缓冲/日常章），直接**原样吐回【已有人物档案】**（一字不差），不做任何改动。审核端会识别这种情况并放行。

请直接输出合流后的完整档案 markdown。"""


# ── 审核提示词 ────────────────────────────────────────────────────────────────
#
# 宽松版审核。**显式声明不检查** Phase 1 的硬清单（卡司配额/双层人设/能力底牌契约/
# 力量体系归属），避免与 CHARACTER_PROFILES_REVIEW_PROMPT 语义串接、把发现流程
# 打回死循环。只查三点核心契约。

CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT = """请审核以下「本章角色档案发现」草稿。这是每章正文完成后的**增量补录**，不是 Phase 1 的初版档案生成——因此审核标准是宽松的。

【草稿】
{draft}

---

## 审核范围（只查以下三点）

1. **保真检查**（最重要）：草稿是否保留了输入档案的**所有原有角色条目原样**？
   - 已有主角/核心配角/反派条目是否原样保留（未被 LLM 压缩/总结/重写措辞）？
   - 已有角色的既定人设（性格底色、立场归属、能力上限）是否被改写？（只允许在条目末尾追加"【本章新增】…"补充段，不允许改动原有文字）
   - 保真失败即打回。

2. **反幻觉检查**：草稿新增的角色 / 新暴露信息，是否确实来自本章正文？
   - 若草稿的"新增"内容看起来是 LLM 推测/演绎，而非本章正文显式描写，指出并要求删除。
   - 若草稿写"本章无新增"（即原样吐回已有档案），只要保真无失即放行。

3. **格式合理性**：新增段的插入位置是否合理（同类角色附近，或独立"本章新增"小节挂在文末）？是否夹杂了正文情节、code fence、元叙述？

## 明确**不检查**的项（防串接 Phase 1 硬清单）

以下项**不属于本审核范围**，即使草稿缺失也**不打回**：

- ❌ 卡司配额（多少主角/多少配角/多少反派）
- ❌ 双层人设（表层公开人设 + 深层隐藏人设）
- ❌ 四卷成长弧光 / 初始锚点 / 四卷成长天花板
- ❌ 能力/底牌契约（能力归属力量体系哪一层/流派）
- ❌ 篇幅 500-2000 字之类的字数下限

理由：这些是 Phase 1 初版档案的硬清单；本环节是 Phase 2 阶段的次要角色补录，允许简洁留白。

## 判定

三点全通过 → 直接回复「无问题」；任何一点不合格 → 逐条列出问题 + 改法。"""


# ── 组装函数 ──────────────────────────────────────────────────────────────────

def character_profiles_discover_prompt(state: "NovelState") -> str:
    """组装本章「角色档案发现」生成提示词。

    Args:
        state: NovelState 或 EditStepSubState 子类实例。需要以下字段：
            - total_chapters_written: int（1-based 全书章号，save_chapter 已自增）
            - character_profiles: str（已有人物档案，Phase 1 生成 + 前几章 discover 累积）
            - current_draft: str（本章正文，save_chapter 之后仍保留、未被清空）
    """
    chapter_num = state.total_chapters_written
    # save_chapter 后 total_chapters_written 已自增到本章号；此处即"刚写完的本章号"
    existing_profiles = state.character_profiles or "（尚无人物档案）"
    chapter_draft = state.current_draft or "（本章正文缺失）"
    return CHARACTER_PROFILES_DISCOVER_PROMPT.format(
        chapter_num=chapter_num,
        existing_profiles=existing_profiles,
        chapter_draft=chapter_draft,
    )
