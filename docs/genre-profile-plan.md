# 题材风格档案（Genre Profile）拆分方案

## 一、背景与问题

### 1.1 现状

当前系统的所有提示词（`prompts.py`、`context.py`）中**硬编码了"日系轻小说"风格**，无论用户输入什么 `genre`（题材），生成的文风完全相同。

具体表现为：

- `chapter_prompt` 开头写死"你是深耕日系轻小说创作多年的知名职业作家"
- 文体风格规则写死"标准日系轻小说"的细则（内心吐槽、漫改镜头感等）
- `overall_outline_prompt` 写死"擅长轻小说架构的资深作家"
- `CHARACTER_PROFILES_PROMPT` 写死"精通轻小说立体人设"
- `context.py:90` 系统提示词写死"擅长轻小说（ライトノベル）创作"
- `CHAPTER_REVIEW_PROMPT` 审核标准写死"轻小说风格合规性"
- `CHARACTER_PROFILES_REVIEW_PROMPT` 审核身份写死"资深轻小说创作者"

### 1.2 问题

1. **LLM 对日系轻小说的训练不充分**，导致生成质量不稳定，文风不地道
2. **无法支持多题材**：玄幻、都市、悬疑、科幻、言情等题材各有不同的叙事惯例和文风要求，一套硬编码的提示词无法覆盖
3. **`state.genre` 字段形同虚设**：虽然用户输入了题材，但提示词完全忽略它

### 1.3 目标

将提示词拆分为**通用层**（所有题材共享）和**风格层**（按题材切换），建立可扩展的题材风格档案系统，使不同题材能选择不同的文风指令。

---

## 二、核心设计：提示词两层拆分

### 2.1 通用层（题材无关）

以下规则对所有题材都适用，提取为共享常量，不随 genre 变化：

| 规则 | 当前位置 | 说明 |
|------|----------|------|
| 人设严格合规 | `chapter_prompt:136` | 禁止 OOC、人设崩坏、性格矛盾 |
| 剧情与双线要求 | `chapter_prompt:137` | 伏笔承接、明暗双线咬合 |
| 章节节奏 | `chapter_prompt:146` | 章末钩子、结构完整 |
| 世界观合规 | `chapter_prompt:147` | 不新增脱离原著的设定 |
| 去机械化规则 | `chapter_prompt:149-153` | 标志动作不高频复读 |
| 输出硬性规范 | `chapter_prompt:171-177` | 纯正文输出、无批注 |
| 四卷式结构 | `overall_outline_prompt:54` | 起承转合四段式 |
| 双线并行设计 | `overall_outline_prompt:55` | 明暗双线 |
| 留白规则 | `overall_outline_prompt:58` | 不填充微观细节 |
| 人设双层面拆分 | `CHARACTER_PROFILES_PROMPT:73` | 表层+深层人设 |
| 人设自洽 | `CHARACTER_PROFILES_PROMPT:76` | 软肋、缺陷、心理枷锁 |
| 反派分层 | `CHARACTER_PROFILES_PROMPT:79` | 功能性反派 vs 根源反派 |
| 人物关系闭环 | `CHARACTER_PROFILES_PROMPT:80` | 羁绊围绕主角构建 |

### 2.2 风格层（题材相关）

以下内容需要按 genre 切换，提取为 `GenreProfile` 的字段：

| 字段 | 当前位置 | 说明 |
|------|----------|------|
| `writer_identity` | `chapter_prompt:128` | 章节写作的作家身份定位 |
| `style_rules` | `chapter_prompt:138-144` | 文体风格细则（视角、句式、描写侧重等） |
| `visual_rules` | `chapter_prompt:145` | 镜头/画面感/漫改适配规则 |
| `dialogue_rules` | `chapter_prompt:155-159` | 对话占比要求 |
| `example_bad` | `chapter_prompt:161-162` | 错误示例 |
| `example_good` | `chapter_prompt:164-169` | 正确示例 |
| `review_style_check` | `CHAPTER_REVIEW_PROMPT:672-676` | 章节审核的风格检查项 |
| `character_review_identity` | `CHARACTER_PROFILES_REVIEW_PROMPT:632` | 人设审核的身份定位 |
| `character_review_style` | `CHARACTER_PROFILES_REVIEW_PROMPT:640-641` | 人设审核中风格相关检查项（视觉记忆点、双线适配） |
| `system_identity` | `context.py:90` | 系统提示词中的身份定位 |
| `outline_writer_identity` | `overall_outline_prompt:51` | 大纲写作的作家身份定位 |
| `character_writer_identity` | `CHARACTER_PROFILES_PROMPT:65` | 人设写作的身份定位 |
| `character_output_style` | `CHARACTER_PROFILES_PROMPT:85` | 人设输出风格描述 |

---

## 三、`GenreProfile` 数据结构

新建文件 `src/novel_workflow/genre_profiles.py`：

```python
from dataclasses import dataclass

@dataclass
class GenreProfile:
    """题材风格档案：驱动提示词中按题材切换的风格化部分。"""

    # ── 章节写作（chapter_prompt）──────────────────────────
    writer_identity: str          # 作家身份定位
    style_rules: str              # 文体风格细则（替换 chapter_prompt 第3条）
    visual_rules: str             # 镜头/画面感规则（替换第4条）
    dialogue_rules: str           # 对话占比规则（替换对话专项规则段）
    example_bad: str              # 错误示例
    example_good: str             # 正确示例

    # ── 章节审核（CHAPTER_REVIEW_PROMPT）────────────────────
    review_style_check: str       # 章节审核中的风格合规性检查项

    # ── 人设写作（CHARACTER_PROFILES_PROMPT）────────────────
    character_writer_identity: str  # 人设写作的身份定位
    character_output_style: str     # 人设输出风格描述

    # ── 人设审核（CHARACTER_PROFILES_REVIEW_PROMPT）──────────
    character_review_identity: str  # 人设审核的身份定位
    character_review_style: str     # 人设审核中风格相关检查项

    # ── 大纲写作（overall_outline_prompt）────────────────────
    outline_writer_identity: str    # 大纲写作的身份定位

    # ── 系统提示词（context.py）──────────────────────────────
    system_identity: str            # 系统提示词中的身份定位
```

---

## 四、预定义题材列表

### 4.1 初始题材

先建立 `default` 档案（影视化类型小说风格，保留漫改适配能力），后续逐步添加：

| 题材 key | 定位 | 优先级 |
|----------|------|--------|
| `default` | 影视化类型小说，画面感+对话驱动，适配漫改 | **第一步必做** |
| `玄幻` | 升级体系、热血战斗、爽点驱动 | 第二步 |
| `都市` | 现实感、生活化对话、情感细腻 | 第二步 |
| `悬疑` | 悬念铺设、信息控制、节奏紧凑 | 第二步 |
| `科幻` | 硬设定、逻辑严密、世界观展开 | 第二步 |
| `言情` | 情感线为主、心理描写、细腻互动 | 第二步 |

### 4.2 回退策略

```python
def get_genre_profile(genre: str) -> GenreProfile:
    """按题材获取风格档案，未匹配时回退到 default。"""
    return GENRE_PROFILES.get(genre, GENRE_PROFILES["default"])
```

用户输入的 `genre` 不在预定义列表中时，自动回退到 `default` 档案，保证系统不会报错。

---

## 五、改动详情

### 5.1 新建 `src/novel_workflow/genre_profiles.py`

- 定义 `GenreProfile` dataclass
- 定义 `GENRE_PROFILES` 字典，初始只含 `default`
- 定义 `get_genre_profile(genre)` 函数

### 5.2 修改 `src/novel_workflow/prompts.py`

#### `chapter_prompt` 函数（`:118-177`）

**改动**：增加 `genre` 参数，从 `GenreProfile` 取用风格层字段，通用层规则保持硬编码。

```python
def chapter_prompt(title: str, chapter_num: int, all_titles: list[str],
                   chapter_context: str = "", genre: str = "") -> str:
    profile = get_genre_profile(genre)
    # ... 通用层规则不变 ...
    # 风格层从 profile 取用：
    #   profile.writer_identity  替换 :128
    #   profile.style_rules     替换 :138-144
    #   profile.visual_rules    替换 :145
    #   profile.dialogue_rules  替换 :155-159
    #   profile.example_bad     替换 :161-162
    #   profile.example_good    替换 :164-169
```

#### `overall_outline_prompt` 函数（`:49-61`）

**改动**：增加 `genre` 参数，替换身份定位。

```python
def overall_outline_prompt(total_word_count: str, genre: str = "") -> str:
    profile = get_genre_profile(genre)
    # profile.outline_writer_identity 替换 :51 的"擅长轻小说架构的资深作家"
```

#### `CHARACTER_PROFILES_PROMPT` 常量（`:63-86`）

**改动**：从常量改为函数，增加 `genre` 参数。

```python
def character_profiles_prompt(genre: str = "") -> str:
    profile = get_genre_profile(genre)
    # profile.character_writer_identity 替换 :65
    # profile.character_output_style    替换 :85
```

#### `CHAPTER_REVIEW_PROMPT` 常量（`:661-681`）

**改动**：从常量改为函数，增加 `genre` 参数。

```python
def chapter_review_prompt(genre: str = "") -> str:
    profile = get_genre_profile(genre)
    # profile.review_style_check 替换 :672-676 的"轻小说风格合规性"
```

#### `CHARACTER_PROFILES_REVIEW_PROMPT` 常量（`:632-646`）

**改动**：从常量改为函数，增加 `genre` 参数。

```python
def character_profiles_review_prompt(genre: str = "") -> str:
    profile = get_genre_profile(genre)
    # profile.character_review_identity 替换 :632
    # profile.character_review_style    替换 :640-641
```

### 5.3 修改 `src/novel_workflow/context.py`

#### `build_foundation_context` 函数（`:90`）

**改动**：系统提示词身份定位按 `state.genre` 切换。

```python
def build_foundation_context(state: _ContextState, *, exclude_snapshots: bool = False) -> str:
    profile = get_genre_profile(state.genre)
    parts.append(f"{profile.system_identity}\n以下是本次作品的核心设定，请严格遵守：\n")
    # ... 其余不变 ...
```

### 5.4 修改 `src/novel_workflow/subgraph.py`

#### `_REVIEW_PROMPTS` 字典（`:48-62`）

**改动**：`CHAPTER_REVIEW_PROMPT` 和 `CHARACTER_PROFILES_REVIEW_PROMPT` 从常量引用改为函数调用。

当前 `llm_self_review`（`:134-165`）通过 `_REVIEW_PROMPTS[review_type]` 取用审核提示词模板，然后 `.format(draft=...)`。

改动方案：
- `_REVIEW_PROMPTS` 中对 `chapter` 和 `character_profiles` 两个 key 存储函数而非字符串
- `llm_self_review` 中判断：如果取到的是函数，先调用 `fn(genre)` 得到模板字符串，再 `.format(draft=...)`
- 需要将 `genre` 传入 `ReviewSubState`（或通过 `system_context` 间接获取）

具体实现：

```python
# subgraph.py 中 _REVIEW_PROMPTS 改为：
_REVIEW_PROMPTS = {
    "foundation": FOUNDATION_REVIEW_PROMPT,       # 常量，不变
    "core_theme": CORE_THEME_REVIEW_PROMPT,       # 常量，不变
    # ... 其他常量不变 ...
    "chapter": chapter_review_prompt,             # 改为函数引用
    "character_profiles": character_profiles_review_prompt,  # 改为函数引用
}

# llm_self_review 中：
review_template = _REVIEW_PROMPTS.get(state.review_type, FOUNDATION_REVIEW_PROMPT)
if callable(review_template):
    review_template = review_template(state.genre)  # 先按题材生成模板
review_prompt = review_template.format(draft=state.current_draft)
```

### 5.5 修改 `src/novel_workflow/state.py`

#### `ReviewSubState`（子图状态）

**改动**：增加 `genre` 字段，供 `llm_self_review` 使用。

```python
@dataclass
class ReviewSubState:
    # ... 现有字段 ...
    genre: str = ""    # 新增：题材，供审核提示词按题材切换
```

#### `NovelState`（主图状态）

**无需改动**：`genre` 字段已存在（`:27`）。

#### 子图桥接字段同步

`ChapterEditSubState`、`ArcEditSubState`、`EditStepSubState` 中均需增加 `genre` 字段，确保从父图映射到子图时 `genre` 能传递下去。

涉及文件：
- `chapter_edit_subgraph.py:49` — 已有 `genre` 字段，无需改动
- `arc_edit_subgraph.py:43` — 已有 `genre` 字段，无需改动
- `edit_step_subgraph.py:64` — 已有 `genre` 字段，无需改动

> 上述三个子图状态已经包含 `genre` 字段，只需确认 `ReviewSubState` 也加上即可。

### 5.6 修改 `src/novel_workflow/nodes/foundation.py`

#### `prepare_overall_outline`（`:47-53`）

**改动**：传入 `genre`。

```python
def prepare_overall_outline(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": overall_outline_prompt(state.total_word_count, state.genre),
        "review_type": "overall_outline",
        "genre": state.genre,  # 新增：传递给子图
        **reset_review_fields(),
    }
```

#### `prepare_character_profiles`（`:56-62`）

**改动**：`CHARACTER_PROFILES_PROMPT` 从常量改为函数调用。

```python
def prepare_character_profiles(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_profiles_prompt(state.genre),
        "review_type": "character_profiles",
        "genre": state.genre,  # 新增
        **reset_review_fields(),
    }
```

> 其他 `prepare_*` 节点（core_theme、world_building、core_conflicts）也需加上 `"genre": state.genre`，因为 `ReviewSubState` 新增了 `genre` 字段，需要从父图映射进去。

### 5.7 修改 `src/novel_workflow/nodes/chapter.py`

#### `prepare_chapter`（`:69-75`）

**改动**：传入 `genre`。

```python
def prepare_chapter(state: NovelState) -> dict:
    # ...
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": chapter_prompt(title, chapter_num, merged_titles, chapter_context, state.genre),
        "review_type": "chapter",
        "genre": state.genre,  # 新增
        **reset_review_fields(),
    }
```

### 5.8 修改前端 `UserInputsForm.tsx`

**改动**：`genre` 字段从文本输入框改为下拉选择框。

```tsx
// 对 genre 字段特殊处理：渲染 <select> 而非 <input>
const SELECT_FIELDS: Record<string, string[]> = {
  genre: ["default", "玄幻", "都市", "悬疑", "科幻", "言情"],
};

// 渲染逻辑：
{SELECT_FIELDS[k] ? (
  <select value={values[k]} onChange={...}>
    {SELECT_FIELDS[k].map(opt => <option key={opt} value={opt}>{opt}</option>)}
  </select>
) : (
  <input type="text" ... />
)}
```

> `default` 选项显示为"通用/影视化"。

### 5.9 修改 `src/novel_workflow/nodes/inputs.py`

**改动**：`genre` 字段说明更新为预定义选项提示。

```python
"genre": "小说类型（可选：玄幻、都市、悬疑、科幻、言情、通用）",
```

---

## 六、不需要改动的提示词

以下审核提示词只检查格式、结构、逻辑，与文风无关，**不需要按 genre 适配**：

| 提示词 | 位置 | 原因 |
|--------|------|------|
| `CORE_THEME_REVIEW_PROMPT` | `:579-590` | 只检查主题清晰度、字数 |
| `WORLD_BUILDING_REVIEW_PROMPT` | `:592-603` | 只检查世界观完整性、自洽性 |
| `CORE_CONFLICTS_REVIEW_PROMPT` | `:605-616` | 只检查冲突层次、类型 |
| `OVERALL_OUTLINE_REVIEW_PROMPT` | `:618-630` | 只检查四卷结构、因果逻辑 |
| `FOUNDATION_REVIEW_PROMPT` | `:648-659` | 通用质量审核 |
| `TITLES_REVIEW_PROMPT` | `:683-698` | 只检查标题数量、格式 |
| `ARC_OUTLINE_REVIEW_PROMPT` | `:705-721` | 只检查弧线大纲格式、字数 |
| `CHARACTER_STATUS_REVIEW_PROMPT` | `:725-737` | 只检查格式、字段完整性 |
| `CHARACTER_RELATIONS_REVIEW_PROMPT` | `:739-750` | 只检查格式、准确性 |
| `FORESHADOWING_REVIEW_PROMPT` | `:752-771` | 只检查 JSON 格式、伏笔逻辑 |
| `PHASE_SUMMARY_REVIEW_PROMPT` | `:822-833` | 只检查格式、字段完整性 |

以下生成提示词也不涉及文风，**不需要改动**：

| 提示词 | 位置 | 原因 |
|--------|------|------|
| `CORE_THEME_PROMPT` | `:20-27` | 只要求阐述主题，无风格要求 |
| `WORLD_BUILDING_PROMPT` | `:29-37` | 只要求描述世界观，无风格要求 |
| `CORE_CONFLICTS_PROMPT` | `:39-47` | 只要求设计冲突，无风格要求 |
| `titles_prompt` | `:90-115` | 只生成标题，无风格要求 |
| `arc_outline_prompt` | `:195-242` | 只规划弧线大纲，无风格要求 |
| `character_status_prompt` | `:245-271` | 只更新状态快照，无风格要求 |
| `character_relations_prompt` | `:274-301` | 只更新关系快照，无风格要求 |
| `foreshadowing_prompt` | `:466-528` | 只更新伏笔台账，无风格要求 |
| `phase_summary_prompt` | `:531-558` | 只更新固化数据，无风格要求 |
| `SUMMARY_PROMPT` | `:561-574` | 只生成章节摘要，无风格要求 |

---

## 七、实施步骤

### 第一步：抽象基础结构（本次实施）

1. 新建 `src/novel_workflow/genre_profiles.py`
   - 定义 `GenreProfile` dataclass
   - 定义 `default` 档案（影视化类型小说风格，保留漫改适配）
   - 定义 `get_genre_profile()` 函数

2. 修改 `prompts.py`
   - `chapter_prompt` 增加 `genre` 参数，风格层从 profile 取用
   - `overall_outline_prompt` 增加 `genre` 参数
   - `CHARACTER_PROFILES_PROMPT` 改为函数 `character_profiles_prompt(genre)`
   - `CHAPTER_REVIEW_PROMPT` 改为函数 `chapter_review_prompt(genre)`
   - `CHARACTER_PROFILES_REVIEW_PROMPT` 改为函数 `character_profiles_review_prompt(genre)`

3. 修改 `context.py`
   - `build_foundation_context` 按 `state.genre` 切换系统提示词身份定位

4. 修改 `state.py`
   - `ReviewSubState` 增加 `genre` 字段

5. 修改 `subgraph.py`
   - `_REVIEW_PROMPTS` 中 `chapter` 和 `character_profiles` 改为函数引用
   - `llm_self_review` 支持函数型审核模板

6. 修改 `nodes/foundation.py`
   - 所有 `prepare_*` 节点增加 `"genre": state.genre`
   - `prepare_overall_outline` 和 `prepare_character_profiles` 调用方式更新

7. 修改 `nodes/chapter.py`
   - `prepare_chapter` 传入 `genre` 并增加桥接字段

8. 修改前端 `UserInputsForm.tsx`
   - `genre` 字段改为下拉选择

9. 修改 `nodes/inputs.py`
   - `genre` 字段说明更新

### 第二步：逐步填充题材（后续迭代）

在 `GENRE_PROFILES` 字典中逐个添加题材档案：

```python
GENRE_PROFILES = {
    "default": GenreProfile(...),   # 第一步已完成
    "玄幻": GenreProfile(...),      # 第二步
    "都市": GenreProfile(...),      # 第二步
    "悬疑": GenreProfile(...),      # 第二步
    "科幻": GenreProfile(...),      # 第二步
    "言情": GenreProfile(...),      # 第二步
}
```

每新增一个题材只需在 `genre_profiles.py` 中添加一个 `GenreProfile` 条目，**不需要修改任何 prompt 函数或节点代码**。

---

## 八、修改文件汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/novel_workflow/genre_profiles.py` | **新建** | `GenreProfile` 数据结构 + `default` 档案 + `get_genre_profile()` |
| `src/novel_workflow/prompts.py` | 修改 | 5 个提示词改为按 genre 取用风格片段 |
| `src/novel_workflow/context.py` | 修改 | 系统提示词身份定位按 genre 切换 |
| `src/novel_workflow/state.py` | 修改 | `ReviewSubState` 增加 `genre` 字段 |
| `src/novel_workflow/subgraph.py` | 修改 | 审核提示词支持函数型模板 |
| `src/novel_workflow/nodes/foundation.py` | 修改 | `prepare_*` 节点传递 `genre` |
| `src/novel_workflow/nodes/chapter.py` | 修改 | `prepare_chapter` 传递 `genre` |
| `src/novel_workflow/nodes/inputs.py` | 修改 | `genre` 字段说明更新 |
| `frontend/src/components/interrupts/UserInputsForm.tsx` | 修改 | `genre` 改为下拉选择 |

---

## 九、验证步骤

1. `langgraph dev` 启动无报错
2. 创建线程，触发 `collect_user_inputs` 中断，`genre` 字段显示为下拉选择
3. 选择 `default`（通用），完成基础设定流程，检查生成内容是否为影视化类型小说风格
4. 检查 `chapter_prompt` 输出中不再出现"日系轻小说"字样
5. 检查 `CHAPTER_REVIEW_PROMPT` 审核标准与生成风格一致
6. 检查 `CHARACTER_PROFILES_REVIEW_PROMPT` 审核身份不再出现"轻小说"
7. 检查 `context.py` 系统提示词身份定位已切换
8. 后续添加新题材档案后，选择不同 `genre` 能生成不同文风
