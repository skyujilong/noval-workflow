"""章级 scene beats 提示词与组装函数。

Scene beats 是章前节拍表(可跳步骤),把章纲的 4 字段(目标/阻碍/结果/代价)细化成
3–7 个结构化 beat,并把「打脸四拍 / 章尾钩 / 三段式爽感闭环」这些散落在 chapter_prompt
里的 doctrine 上升为 beat 上的 device_tags 硬约束枚举,让 LLM 无法绕开。

与 arc_outline(批次弧线)的职责边界:
- arc_outline 说"这批 5 章要走完 A→B→C 弧线"(章间层,每批一次)
- scene_beats 说"本章内部怎么用 5 个 beat 演出 A→A.5 这一段"(章内层,每章一次)

落地位置:scene_beats_step → prepare_chapter;save_chapter 之后由 chapter loop 清零,
防止下一章跳过 gate 时误用上一章的 beats(详见 state.py::beats_chapter_index 注释)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from noval_workflow.prompts.base import (
    _extract_arc_chapter_block,
    evolved_directives_block,
    get_evolved_directives,
)
from noval_workflow.prompts.registry import get_prompt_pack

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


# ── device_tag 枚举与文字说明(LLM prompt 里引用;save/review 校验也读它)─────────

# 「打脸四拍」的四个 tag——出现任一即视为打脸桥段,硬约束「四拍必须齐全」。
SLAP_TAGS = ("slap_taunt", "slap_silence", "slap_crush", "slap_witness")

# 「三段式爽感闭环」的三个 tag——单个爽点从压抑→蓄势→释放。
CATHARSIS_TAGS = ("setup", "buildup", "release")

# 钩子:开篇钩仅在章号 1 的首 beat 才合规;章尾钩必须挂在末 beat。
HOOK_TAGS = ("hook_opening", "hook_chapter_end")

# 伏笔:埋点 / 回收。
FORESHADOW_TAGS = ("foreshadow_plant", "foreshadow_recover")

# 缓冲:日常场景,防紧绷疲劳。
BUFFER_TAGS = ("buffer",)

# 全部合法 device_tag 集合——save/review 拿它做枚举校验。
ALL_DEVICE_TAGS = frozenset(SLAP_TAGS + CATHARSIS_TAGS + HOOK_TAGS + FORESHADOW_TAGS + BUFFER_TAGS)


# ── 共享 spec 块(生成/审核唯一真源)──────────────────────────────────────────
#
# 「字段规范 + device_tags 枚举 + 硬约束」抽成共享文本,SCENE_BEATS_PROMPT 与
# SCENE_BEATS_REVIEW_PROMPT 都用 str.replace 拼进去。生成端拿它教 LLM 怎么产出;
# 审核端拿它对照草稿判定——避免两处叙述各自漂移。
#
# 里面所有 JSON 字面花括号仍用 {{ }} 转义,拼进最终 prompt 后被 .format() 归一为
# 字面 { },同时不影响 {chapter_num} / {draft} 等占位符。

_BEATS_SPEC = """## 单个 beat 的字段(严格 JSON,缺一不可)

```json
{{
  "id": 1,
  "scene": "时/地/主要出场人物(≤20字)",
  "goal": "本 beat 主角要做什么(≤30字)",
  "obstacle": "阻碍/冲突(≤30字;无外部冲突时写内在犹豫/氛围压力/信息差,不强行制造硬冲突)",
  "outcome": "结果:成/败/悬置——必须带具体状态变化(位置/关系/信息/认知/情绪/资源任一即可,不要求事件推进),禁止「聊完就散」(≤30字)",
  "cost": "付出的代价或情绪损耗——即使成功也有微损耗,缓冲/日常 beat 可以是时间/机会成本/心境变化(≤30字)",
  "emotion_arc": "情绪走向,如 屈辱→蓄力 / 麻木→爆发 / 松弛→微紧(≤20字)",
  "pacing": "slow / medium / fast(决定本段的展开密度:slow 重感官/心理/对话细节,允许慢镜;medium 平衡叙事;fast 短句推进动作/转折)",
  "prose_focus": "本段重点展开的维度:动作/对话/心理/感官/氛围/信息交换(≤15字)",
  "device_tags": ["setup"],
  "target_words": 800
}}
```

字段字数硬限:scene ≤20、goal/obstacle/outcome/cost ≤30、emotion_arc ≤20、prose_focus ≤15。

## device_tags 枚举(每 beat 至少 1 个,只能从下表选)

### 三段式爽感闭环(单个爽点桥段的三段结构)
- `setup`:压抑铺陈——把不公/嘲讽/危机写具体,越具体后面越爽
- `buildup`:蓄势——主角隐忍/布局/觉醒,张力积累
- `release`:释放——爽感外显,打脸/翻盘/碾压

### 打脸四拍(打脸桥段必用,缺一不可)
- `slap_taunt`:嘲讽——反派/众人看不起主角,越嚣张越好
- `slap_silence`:沉默——主角不辩解,淡淡出手(蓄势张力)
- `slap_crush`:碾压——实力/真相/反转一击致命
- `slap_witness`:围观——旁观者的震惊反应(最容易漏的一拍,但最爽)

### 钩子
- `hook_opening`:开篇钩——仅在**第 1 章的首 beat** 才能使用(3 句内立危机/反差)
- `hook_chapter_end`:章尾钩——**只能挂在最后一个 beat 上**,在情绪/动作最高点前一秒断章

### 伏笔
- `foreshadow_plant`:埋点——本 beat 首次埋下的伏笔线索
- `foreshadow_recover`:回收——兑现前文埋下的伏笔

### 节奏
- `buffer`:缓冲/日常/铺垫/回落——紧张段之间的舒缓,防读者疲劳;承担人物生活化互动、氛围铺陈、心理沉淀、信息释放、小伏笔静置;不必有强冲突,把人写活、把世界写具体本身就是叙事任务
- `pacing`(beat 字段,不是 tag):控制本段展开密度——`slow` 用于情绪爆点前的蓄势、人物独处、氛围铺垫、关键对话,允许写生理反应、感官细节、对话停顿、沉默与动作留白;`medium` 用于日常推进、信息交换;`fast` 用于战斗、突发危机、连续反转,用短句快推。**整章 pacing 必须错落**:禁止所有 beat 全 fast(会喘不过气/事件堆压),也禁止全 slow(会拖);爆发章以 medium+fast 为主、开头/结尾插 slow 蓄势;铺垫/缓冲章以 slow+medium 为主、允许一个 fast 小刺点保张力

## 硬约束(必须满足,否则不合格重来)

1. **打脸四拍完整性**:只要出现任一 `slap_*` 标签,四拍必须**完整齐全** —— 缺任何一拍都不合格;不想做完整四拍就退化用 `release`(普通爽点释放)
2. **章尾钩位置**:`hook_chapter_end` **只能挂在最后一个 beat 上**,不能在中间出现
3. **开篇钩使用**:`hook_opening` **只在第 1 章的第 1 个 beat** 才合规;非第 1 章禁止使用
4. **有进有退**:每个 beat 的 outcome 必须带具体状态变化(人物位置/关系/信息/认知/心境/资源/伤势/情绪任一即可),禁止连续 3 个 beat 都是"悬置"或"聊完就散"。**注意**:铺垫/缓冲/回落 beat 的"变化"可以是内隐的(人物关系微变、读者获得关键信息、情绪基调转换),不要求外部事件推进
5. **pacing 错落(防章章赶进度)**:整章 beats 的 pacing 必须张弛相间——
   - 爆发/转折章:至少 1 个 slow beat(用于开篇铺垫或情绪蓄势),其余 medium+fast,末 beat 前可有 slow 半拍拉长张力再接 hook_chapter_end
   - 铺垫/缓冲/回落章:以 slow+medium 为主,允许 1 个 fast 小刺点保张力,禁止强塞冲突硬凑爽点
   - 推进章:slow/medium/fast 至少各出现 1 次,让节奏呼吸
   - 任何档位的章都**禁止所有 beat 全 fast**,那会导致事件堆叠、人物扁平、读者来不及感受
6. **按档位决定冲突密度**:buffer/pacing=slow 的 beat 不强行制造外部冲突——把它当作"让读者听见角色呼吸、看见世界细节"的窗口,允许写生活质感、感官细节、对话留白、沉默反应
7. **字数分配**:所有 beat 的 target_words 累加应贴近【本章目标字数】(±20% 以内);slow beat 通常分配更多字数(600-1000),fast beat 可短(300-500)
8. **弧线大纲对齐**:整章 beats 必须落实【本章弧线大纲锚点】的档位定位与核心内容;淡章不硬塞爽点/反转,重章不稀释爆点——按档位忠实执行,不抢写后续章节内容"""


# ── 生成提示词 ────────────────────────────────────────────────────────────────
#
# 用 str.replace 而不是 f-string:_BEATS_SPEC 里的 {{ }} 需要留给下游 .format() 处理,
# 拼装期不能被再解释一次。

_SCENE_BEATS_TEMPLATE = """请为本章设计 scene beats——本章正文的场景节拍表,作为下一步正文创作的首要依据。

【本章定位】第 {chapter_num} 章《{title}》{batch_pos_desc}
【本章目标字数】{chapter_word_count}{arc_section}{chapter_context_section}

---

## 任务

输出 **3–7 个 beat** 组成的 JSON 数组:
- 短平快章(日常/过场/铺垫)3–4 个 beat
- 重章(打脸/爆点/身份揭晓/大战)5–7 个 beat

每个 beat 都是一个独立场景/节拍,逐 beat 展开正文,beat 之间用空行分场。

__BEATS_SPEC__

## 输出格式(严格 JSON 数组,无 markdown 围栏)

直接输出如下结构的 JSON 数组,不要包裹在 ```json 里,不要有解释文字:

```
[
  {{"id": 1, "scene": "...", "goal": "...", "obstacle": "...", "outcome": "...", "cost": "...", "emotion_arc": "...", "pacing": "slow", "prose_focus": "氛围/心理", "device_tags": ["setup"], "target_words": 700}},
  {{"id": 2, ...}}
]
```

请直接输出 JSON 数组。"""

SCENE_BEATS_PROMPT = _SCENE_BEATS_TEMPLATE.replace("__BEATS_SPEC__", _BEATS_SPEC)


# ── 审核提示词 ────────────────────────────────────────────────────────────────
#
# 与生成 prompt 共用 _BEATS_SPEC:审核端不再自己重述字段/枚举/硬约束原文,只保留
# 「逐项检查如何判定」。规范源单一,改一处生效两处。

_SCENE_BEATS_REVIEW_TEMPLATE = """请审核以下 scene beats 草稿,逐条检查是否符合硬性规则;无问题则回复「无问题」,有问题则列出具体条目。

【草稿】
{draft}

---

以下是本章 scene beats 必须遵守的规范(生成端使用同一份规范,请对照草稿判定):

__BEATS_SPEC__

---

## 逐项检查(对照上文规范,发现任何一项不合格都要指出,并给出改法)

1. **JSON 合法性**:能否被解析为顶层 list、每个元素都是 dict?字段是否齐全(id / scene / goal / obstacle / outcome / cost / emotion_arc / pacing / prose_focus / device_tags / target_words)?

2. **beat 数量**:3–7 个之间?短平快/铺垫/缓冲场景 3–4、重章 5–7 是否合理?

3. **pacing 合法性与错落**:每个 beat 的 pacing 是否是 `slow` / `medium` / `fast` 之一?是否整章全部 fast(节奏单调堆叠,不合格)?爆发章是否至少有 1 个 slow beat 做蓄势?铺垫/缓冲章是否以 slow+medium 为主?(对照上文硬约束 5)

4. **prose_focus 填写**:是否明确指定了本段展开维度(动作/对话/心理/感官/氛围/信息交换等),避免每段都"什么都写一点"结果什么都没展开?

5. **device_tags 枚举合法性**:所有 tag 是否都在上文枚举内?有任何非枚举值必须指出。

6. **打脸四拍完整性**:只要草稿里出现任一 `slap_*` tag,是否 `slap_taunt` / `slap_silence` / `slap_crush` / `slap_witness` **四拍齐全**?缺任何一拍即视为不合格,必须补齐或整体退化为 `release`。(硬约束 1)

7. **章尾钩位置**:`hook_chapter_end` 是否**只在最后一个 beat** 上出现?出现在中间 beat 上不合格。(硬约束 2)

8. **开篇钩使用**:`hook_opening` 是否只在第 1 章的第 1 个 beat 上出现?非第 1 章使用不合格。(硬约束 3)

9. **有进有退**:每个 beat 的 outcome 是否带具体变化(事件/关系/信息/认知/心境/位置任一即可)?是否有连续 3 个 beat outcome 都是"悬置"或含糊描述?铺垫/缓冲/回落 beat 的"变化"可以是内隐的(关系微变/情绪转换/信息释放),不必强塞外部事件。(硬约束 4、6)

10. **字数累加与 pacing 匹配**:所有 target_words 累加是否贴近本章目标字数(±20%)?slow beat 通常分配较多字数(600-1000),fast beat 较短(300-500);所有 beat 字数均匀相同会导致节奏单调,需要指出。(硬约束 7)

11. **字段字数限制**:对照上文「字段字数硬限」逐字段核对,超限指出。

12. **弧线大纲对齐**:是否落实【本章弧线大纲锚点】的档位定位与核心内容,未越权抢写后续章节?(硬约束 8)

---

严格判定,缺一即为不合格。若全部通过,直接回复「无问题」;否则逐条列出问题并给改法。"""

SCENE_BEATS_REVIEW_PROMPT = _SCENE_BEATS_REVIEW_TEMPLATE.replace("__BEATS_SPEC__", _BEATS_SPEC)


# ── 组装函数 ──────────────────────────────────────────────────────────────────

def scene_beats_prompt(state: "NovelState", chapter_context: str = "") -> str:
    """组装本章 scene beats 生成提示词。

    Args:
        state: NovelState 或 SceneBeatsSubState,需要含 chapter loop 上下文字段
            (total_chapters_written / current_batch_titles / current_chapter_index /
            current_arc_outline / chapter_word_count)。
        chapter_context: 由 build_chapter_context(state) 产出,含近期章节完整/概要。
    """
    chapter_num = state.total_chapters_written + 1
    title = state.current_batch_titles[state.current_chapter_index] if state.current_batch_titles else ""
    batch_pos = state.current_chapter_index + 1
    batch_total = len(state.current_batch_titles)
    batch_pos_desc = f",本批第 {batch_pos}/{batch_total} 章。" if batch_total else "。"

    # 从本批弧线大纲抽本章专属那段(复用 base.py 已有工具函数)
    arc_section = ""
    if state.current_arc_outline and batch_pos:
        block = _extract_arc_chapter_block(state.current_arc_outline, batch_pos)
        if block:
            arc_section = f"\n【本章弧线大纲锚点】\n{block}"
        else:
            arc_section = "\n【本章弧线大纲锚点】见系统提示【本批章节弧线大纲】,请定位到本章对应段落。"

    chapter_context_section = ""
    if chapter_context:
        chapter_context_section = f"\n【前文章节参考】\n{chapter_context}"

    # 历史整改要点(自进化闭环):本书 prompt_overrides 里 scene_beats 桶累积的打回意见提炼。
    # 三桶隔离后,scene_beats 只读自己那份;chapter/arc_outline 的整改若用户显式勾选「分发到」
    # scene_beats,会在 apply 时同步写入本桶——LLM 视角把它当"最高优先级补充规则"读。
    pack = get_prompt_pack(state.genre, state.novel_name)
    directives_section = evolved_directives_block(
        get_evolved_directives(pack.flavor, "scene_beats")
    )

    return SCENE_BEATS_PROMPT.format(
        chapter_num=chapter_num,
        title=title,
        batch_pos_desc=batch_pos_desc,
        chapter_word_count=state.chapter_word_count or "(未设定,按 2000-3000 规划)",
        arc_section=arc_section,
        chapter_context_section=chapter_context_section,
    ) + directives_section


# ── 结构化 beats → markdown 表(供 chapter_prompt 注入下游正文创作使用)──────────

def format_beats_for_chapter_prompt(beats: list[dict]) -> str:
    """把已定稿的 beats JSON 渲染成 markdown 列表,注入 chapter_prompt 里作为「首要依据」。

    输出示例:
        - Beat 1【scene】客栈门口,主角与李三初见
          目标:拿到王家书信 ｜ 阻碍:李三索要银两 ｜ 结果:给了 5 两银子拿到信
          代价:暴露身家 ｜ 情绪:戒备→释然 ｜ 目标字数:500
          device_tags: setup, foreshadow_plant

    LLM 拿到这份「结构化到 beat 的清单」比拿到一段章纲文字更难绕开。
    """
    if not beats:
        return ""
    lines: list[str] = []
    for beat in beats:
        bid = beat.get("id", "?")
        scene = beat.get("scene", "")
        goal = beat.get("goal", "")
        obstacle = beat.get("obstacle", "")
        outcome = beat.get("outcome", "")
        cost = beat.get("cost", "")
        emotion = beat.get("emotion_arc", "")
        tags = beat.get("device_tags", []) or []
        words = beat.get("target_words", "")
        tags_str = ", ".join(tags) if tags else "-"
        pacing = beat.get("pacing", "")
        prose_focus = beat.get("prose_focus", "")
        pacing_str = f" ｜ 节奏:{pacing}" if pacing else ""
        focus_str = f" ｜ 展开重点:{prose_focus}" if prose_focus else ""
        lines.append(
            f"- **Beat {bid}【{scene}】**\n"
            f"  - 目标:{goal} ｜ 阻碍:{obstacle} ｜ 结果:{outcome}\n"
            f"  - 代价:{cost} ｜ 情绪:{emotion}{pacing_str}{focus_str} ｜ 目标字数:{words}\n"
            f"  - device_tags:{tags_str}"
        )
    return "\n".join(lines)


# ── 结构化校验(save_fn 落地后调,也可供 review 阶段程序化辅助)──────────────────

def validate_beats(beats: list[dict]) -> list[str]:
    """程序化检查 beats 是否符合硬约束,返回问题列表(空 = 全部合格)。

    与 LLM 自审配合:LLM 自审偶尔漏检结构性问题,这里做一层确定性兜底,避免非法 beats
    直接注入下游 chapter_prompt。当前只做「fail-loud」检查——把问题写日志,不阻断流程;
    是否阻断流程留给上层决定(若需硬阻断,save_fn 可 raise)。
    """
    problems: list[str] = []
    if not beats or not isinstance(beats, list):
        return ["beats 不是非空 list"]

    slap_seen = {tag: False for tag in SLAP_TAGS}
    last_index = len(beats) - 1

    for idx, beat in enumerate(beats):
        if not isinstance(beat, dict):
            problems.append(f"beat[{idx}] 不是 dict")
            continue
        tags = beat.get("device_tags", []) or []
        if not tags:
            problems.append(f"beat[{idx}] device_tags 为空")
        for tag in tags:
            if tag not in ALL_DEVICE_TAGS:
                problems.append(f"beat[{idx}] device_tag {tag!r} 不在枚举内")
            if tag in SLAP_TAGS:
                slap_seen[tag] = True
            if tag == "hook_chapter_end" and idx != last_index:
                problems.append(f"beat[{idx}] hook_chapter_end 未挂在末 beat(位置 {idx}/{last_index})")
            if tag == "hook_opening" and idx != 0:
                problems.append(f"beat[{idx}] hook_opening 未挂在首 beat(位置 {idx})")

    # 打脸四拍完整性硬约束:任一 slap_* 出现即要求四拍齐全
    if any(slap_seen.values()) and not all(slap_seen.values()):
        missing = [tag for tag, seen in slap_seen.items() if not seen]
        problems.append(f"打脸四拍不齐全,缺 {missing}")

    return problems


__all__ = [
    "SCENE_BEATS_PROMPT",
    "SCENE_BEATS_REVIEW_PROMPT",
    "ALL_DEVICE_TAGS",
    "SLAP_TAGS",
    "CATHARSIS_TAGS",
    "HOOK_TAGS",
    "FORESHADOW_TAGS",
    "BUFFER_TAGS",
    "scene_beats_prompt",
    "format_beats_for_chapter_prompt",
    "validate_beats",
]
