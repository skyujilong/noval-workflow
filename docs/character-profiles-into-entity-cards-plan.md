# 人物档案（character_profiles）并入统一实体卡（entity_cards）· 重构规划

**状态**：待启动（TODO，非当前 sprint）
**创建时间**：2026-07-15
**触发对话**：用户注意到「人工审核 · 人物档案」与章末「人物档案发现」/「实体卡发现」之间存在字段重叠、多路更新可能漂移
**建议执行方式**：新建 `docs/exec-plan-yyyy-mm-dd_hh-mm-ss/` 用 `execute-plan-plus` skill 分批推进（估计 ≥ 15 文件跨前后端）

---

## 一、Context（为什么要做）

### 1.1 现状：两个字段并存，各自章末更新

当前 `NovelState` 里承载人物信息的字段有三个，且各有一套独立的生成/更新节点：

| 字段 | 数据形态 | 生成时机 | 更新时机 |
|---|---|---|---|
| `character_profiles: str` | markdown 长文本 | Phase 1 `prepare_character_profiles`（初版全档案） | 每章章末 `character_profiles_discover_step`（LLM 全量重出、覆盖写） |
| `entity_cards: list[EntityCard]`（type=人物） | 结构化字段（`appearance / speech_style / personality / motivation / relations / abilities` 等） | 每章章前 `entity_cards_step`（本章登场实体建卡） | 每章章末 `entity_discover_step`（更新 status/owner/motivation，可新增卡） |
| `character_status: str` / `character_relations: str` | markdown 快照 | 每 STRIDE 章一次快照维护节点 | 快照节点覆盖 |

### 1.2 症状：字段重叠 + 多路 LLM 生成 → 漂移风险

**同一份「人物性格 / 动机 / 能力 / 关系」信息，被两个不同章末节点各自写一遍**：

- `character_profiles_discover_step` 会在 markdown 里追加或改写主角的性格/动机/能力/关系描述
- `entity_discover_step` 会更新 `EntityCard.personality / motivation / abilities / relations` 字段

两次章末 LLM 生成独立进行、独立自审 + 人工审。若用户对第一次审松、第二次审严（或反过来），**同一角色的性格/动机会在两处出现不一致**。下一章：
- `chapter_prompt` 通过 `format_cards_for_chapter_prompt` 从 `entity_cards` 拿"沉默寡言"
- `system_context` 通过 `build_foundation_context` 从 `character_profiles` 拿"外冷内热"
- LLM 同时看到两个信息源 → 输出信息漂移的正文

### 1.3 装备/技能的现状（对照）

**装备/物品**：**没有并存问题**。`state.py:66-67` 已明确「本卡是装备/物品的**唯一真源**（phase_summary 不再存装备）」——`character_profiles` 里若写到主角持有的装备，只是叙事上的一句提及，不作为数据源被下游消费。

**技能/能力**：**部分并存**。`character_profiles` 的 Phase 1 硬清单要求写「能力/底牌契约」；`EntityCard.abilities` 字段也有；两处都可能被 LLM 章末补录。

### 1.4 用户的架构直觉

> "我觉得人物和物品应该是小说的资产。应该抽出去吧？也就是我们的 character_profiles 应该也是 entity_cards 的类型和相关的那个字段。"

用户识别到的是**「唯一真源」（single source of truth）原则**——小说资产（人物 + 装备 + 物品 + 势力 + 地点）应统一由 `entity_cards` 承载；`character_profiles` 是历史演进的债，先有 markdown 全档案、后加了结构化实体卡，但没把「人物」type 从 markdown 迁走。

### 1.5 目标形态

```
小说资产（唯一真源 = entity_cards）
├─ type=人物 (含主角/核心配角/反派/次要角色/NPC 全都在这里)
├─ type=装备
├─ type=物品
├─ type=势力
└─ type=地点

character_profiles 字段    → 删除
character_profiles_discover 章末节点 → 删除（并入 entity_discover）
```

---

## 二、核心设计问题（动手前需先决策）

### 2.1 EntityCard.人物段 字段扩充策略

现有 `EntityCard`（`state.py:59-91`）type=人物 已有：`appearance / speech_style / personality / motivation / relations / abilities / summary`。

对照 Phase 1 `character_profiles` 硬清单（`prompts/review_shared.py:97-107`），差距：

| Phase 1 硬清单项 | EntityCard 是否覆盖 |
|---|---|
| 背景履历 | ❌ 缺 |
| 性格特质 / 行为动机 | ✅ personality / motivation |
| 原生弱点 / 核心诉求 | ❌ 缺 |
| **四卷阶段性成长弧光** | ❌ 缺（关键、长文本） |
| 视觉 & 记忆点 | ✅ appearance |
| **表层公开人设 + 深层隐藏暗线人设**（双层人设） | ⚠️ 只有 appearance/personality，无隐藏层 |
| **能力/底牌契约**（初始锚点 + 四卷成长天花板 + 底牌触发/反噬） | ⚠️ 只有 abilities 一个笼统字段 |

**两条路**（动手前必须选一条）：

- **路 A（细粒度扩展）**：加多个字段 `background / weakness / core_desire / growth_arc / hidden_persona / ability_ceiling / trump_card` 到 EntityCard.人物段
  - 优点：每字段有明确职责，前端可分卡片区块渲染
  - 缺点：字段数量翻倍，序列化 dict 变胖；老 state 快照反序列化对多个新字段各自走默认值

- **路 B（一个长文本兜住）** ⭐ **推荐**：加 `deep_dossier: str = ""` 一个字段承载「主要角色的深度铺陈」（markdown 长文本，仅主要角色填，次要角色留空）
  - 优点：EntityCard schema 侵入小；老 state 快照迁移简单
  - 缺点：`deep_dossier` 内部结构由 prompt 约定，靠 LLM 遵守；无字段级审核

**推荐路 B** 的理由：`character_profiles` 现在也是 markdown 长文本；本次重构核心目的是**统一到一个字段**，而不是**引入更结构化的 schema**（那是另一个话题）。深度铺陈天然适合 markdown 承载。

### 2.2 Phase 1 初版生成的改造策略

现在 `prepare_character_profiles` 一次性出整块 markdown，用户审一次通过 → 落 `state.character_profiles`。

改造后有两条路：

- **路 A（一步到位）**：`prepare_character_profiles` 直接改为生成 **JSON 数组**（type=人物 的 EntityCard 列表，含 `deep_dossier`），审核走 volumes 同款「JSON 卡片视图 + 打回」
  - 优点：Phase 1 结束就是纯结构化状态
  - 缺点：LLM 出 JSON 比出 markdown 更容易结构错误、审核时字段可编辑面更大

- **路 B（渐进）**：保留 markdown 生成 + 加一个「解析节点」把 markdown 拆成 EntityCard 列表
  - 优点：Phase 1 prompt 保持不变（不影响 review_shared.py::CHARACTER_PROFILES_REVIEW_PROMPT 的成熟规则）
  - 缺点：解析节点是新的失败点；markdown → 结构化解析规则难写稳（LLM 输出格式漂移会打回或丢字段）

**推荐路 A**：既然要重构就一步到位，避免留一个「markdown → JSON 解析」的模糊中间层。审核走 EntityCard 卡片视图（复用 volumes 卡片审核范式）。

### 2.3 章末 discover 节点的合并策略

`character_profiles_discover` 与 `entity_discover` 合并后，章末只剩一个节点：

**方案**：**扩展 `entity_discover_step`** 承担两职：
- 现有职责：更新已有卡的 status/owner/motivation
- 新增职责：**为已有主要角色卡追加 `deep_dossier` 增量** —— 提示词加一个 `deep_dossier_delta` 字段（本章新暴露的深度铺陈信息，如「本章揭示身世为 XX 转世」/「本章底牌反噬代价首次暴露」）；save 端把 delta 追加到已有卡的 `deep_dossier` 尾部

好处：章末只走一次 LLM 生成 + 自审 + 人工审，用户只审一次；无双路漂移。

### 2.4 老 state 迁移策略

已跑的 thread（含线上正在跑的小说）里 `state.character_profiles` 是长文本。有三条路：

- **路 A（脚本迁移）**：写一次性脚本，把每个 thread 的 character_profiles markdown 拆解 → 补进对应 entity_cards → 清空 character_profiles
  - 优点：老小说无缝跑
  - 缺点：拆解不稳（LLM 输出格式历史漂移），可能丢信息

- **路 B（不迁移，只对新 thread 生效）** ⭐ **推荐**：老 thread 里 character_profiles 保留原值不动；新代码里 `build_foundation_context` 加兼容分支——若 `entity_cards` 有 type=人物 的卡就走新路径，否则退化到读 `character_profiles`
  - 优点：老小说继续按老逻辑跑完；新小说走新架构；无破坏性变更
  - 缺点：需保留 character_profiles 字段过渡期（数月），字段真正删除要等所有老小说跑完

- **路 C（推倒重来）**：不管老 thread，删字段 + 强制新 thread
  - 缺点：老小说数据丢失，不可接受

**推荐路 B**：保留 character_profiles 字段作为「废弃标记」，只删生成/更新节点；`build_foundation_context` 加分支适配新老 state。等所有老小说完结后再删字段。

### 2.5 canon 锁如何扩展到新字段

现在 `nodes/entity_cards.py::_merge_cards` 对已有卡走「canon 锁」——除 status/owner/motivation 三个动态字段外的字段一律不改写。

新增 `deep_dossier` 后：
- 是否 canon 锁？**推荐 NO**——`deep_dossier` 天然是「增量追加」语义（章末 discover 追加新暴露信息），若 canon 锁则永远无法扩写
- 保护规则：`entity_discover` 的 update 分支允许 `deep_dossier` 变更，但**只能追加**（新值必须以旧值为前缀），不能改写既有内容

需在 `_apply_updates` 里加校验：若新 `deep_dossier` 不以旧值开头 → 拒绝更新 + warn 日志。

---

## 三、影响面清单（≥ 15 文件跨前后端）

### 3.1 后端

**改动**：
- `state.py` — EntityCard 加 `deep_dossier` 字段；NovelState.character_profiles 保留但注释「废弃字段，向后兼容」
- `nodes/foundation.py::prepare_character_profiles / save_character_profiles` — 重写为 JSON 卡片生成 + 逐条 `EntityCard(**c)` 落库到 `entity_cards`
- `nodes/entity_cards.py::_prepare_entity_discover / _save_entity_discover` — prompt 加 `deep_dossier_delta` 字段；save 端追加到已有卡
- `nodes/entity_cards.py::_apply_updates` — 加 deep_dossier「只追加」校验
- `context.py::build_foundation_context` — 从 entity_cards 筛选 type=人物 → 渲染 markdown；兼容分支处理老 state
- `graph.py` — 删 `character_profiles_discover_step` 节点 + 相关边
- `nodes/consistency.py` — 读源改为 entity_cards（type=人物）
- `prompts/base.py` — `character_profiles_prompt` 改为 JSON schema prompt（照 volumes_prompt 模板）
- `prompts/character_profiles_discover.py` — **整个删除**
- `prompts/review_shared.py::CHARACTER_PROFILES_REVIEW_PROMPT` — 改为审核 EntityCard JSON 数组（照 VOLUMES_REVIEW_PROMPT 模板）
- `subgraph.py::_REVIEW_PROMPTS` — `character_profiles_discover` 键删除
- `interrupt_types.py::_REVIEW_TYPE_TO_INTERRUPT_TYPE` — `character_profiles_discover` 键删除
- `character_profiles_discover_subgraph.py` — **整个删除**

**测试**：
- `tests/unit_tests/test_character_profiles_node.py`（新增）— 覆盖 Phase 1 JSON 生成/落库
- `tests/unit_tests/test_entity_discover_deep_dossier.py`（新增）— 覆盖 deep_dossier 增量追加
- 删除 `test_character_profiles_discover_*.py`（如有）

### 3.2 前端

**改动**：
- `types.ts` — EntityCard 加 `deep_dossier?: string`；NovelState.character_profiles 加 `@deprecated` 注释
- `lib/editableState.ts` — EditableTextKey 删 `character_profiles`；`parseEntityCardsJson` 加 `deep_dossier` 字符串字段校验
- `lib/interruptTypes.ts` — FormKind / TYPE_TO_FORM 里 character_profiles_discover 相关删除
- `components/state/StateEditPanel.tsx` — 删 character_profiles textarea 字段块
- `components/interrupts/HumanReviewForm.tsx` — `review_type === "character_profiles"` 分支改走 EntityCard 卡片视图（新组件）
- `components/interrupts/CharacterProfilesCards.tsx`（新增）— 复用 volumes 卡片范式，展示 type=人物 的 EntityCard 列表 + deep_dossier
- `components/state/EntityCardsReadonly.tsx` — 主要角色卡展开 deep_dossier

**测试**：
- 手工验收覆盖：Phase 1 审核抽屉 / 章末 entity_discover 审核 / state 抽屉观测 deep_dossier

### 3.3 迁移文档

- `docs/exec-plan-.../migration-notes.md` — 明确「老 thread 保留 character_profiles，新 thread 走 entity_cards」；给出兼容分支代码位置

---

## 四、验收路径

### 4.1 自动化门禁

```
uv run pytest -x -q                        # 后端全量单测
uv run pyright                             # 后端类型检查
cd frontend && pnpm tsc --noEmit           # 前端类型检查
cd frontend && pnpm build                  # 前端构建
```

新增单测重点：
- Phase 1 JSON 生成 → 卡片视图渲染 → 校验规则打回 → 落库形态与 entity_cards 一致
- entity_discover 生成 deep_dossier_delta → save 端只追加 → canon 锁校验拒绝改写既有内容
- `build_foundation_context` 兼容分支：老 state（有 character_profiles、无 entity_cards）走老路径；新 state 走 entity_cards 路径

### 4.2 手工端到端验收

**场景 A：新小说走 Phase 1 → 章末**
1. `make dev` 启动前后端
2. 新建小说走脑爆 → 基础设定 → 到达「人物档案」审核步骤
3. **应观察**：审核抽屉展示 EntityCard 卡片视图（含主角深度铺陈 deep_dossier 展开区），非 markdown 一坨
4. 通过后进入正文创作；章前 `entity_cards_step` 只补新登场次要角色（不重复建主要角色卡）
5. 章末只出现一次「实体发现」审核（原 character_profiles_discover 已消失），审核抽屉里可看到主要角色的 `deep_dossier_delta`（本章新暴露的深度铺陈）
6. 通过后打开「编辑当前状态」抽屉 → entity_cards 卡片区展开主要角色卡 → 应看到 deep_dossier 已追加本章 delta

**场景 B：老 thread 兼容性**
1. 打开一个 volumes 分支合并前跑到中期的老 thread（如"封魔城的弃子"）
2. 继续推进任意一章
3. **应观察**：`character_profiles` 字段保持不变（不被清空、不被覆盖）；`build_foundation_context` 走老路径读它；无报错

**场景 C：deep_dossier canon 锁**
1. 手工在「编辑当前状态」抽屉里改主角卡的 deep_dossier：删除中间一段
2. 保存 → **应观察**：保存失败 or 保存成功但下次章末 discover 时 warn 日志「deep_dossier 非追加变更」
   - 这一步细节留待实现时决策：保存拦截 or 后置审计

### 4.3 用户可复现验收步骤

1. 新建小说 → Phase 1 到人物档案审核 → 看到 EntityCard 卡片视图（有 deep_dossier 展开区）
2. 通过审核后跑第一章 → 章末只弹一次「实体发现」审核（不再有独立的「人物档案发现」）
3. 打开「编辑当前状态」→ entity_cards 主要角色卡里能看到 deep_dossier
4. `character_profiles` 字段在 state 抽屉里消失（或标注「废弃」）

---

## 五、风险清单

| 风险 | 处理策略 |
|---|---|
| LLM 从零出 EntityCard JSON 数组格式不稳（Phase 1 首次） | 参照 volumes_prompt 严格 JSON schema 约束 + 审核端 fail-fast 打回重生成；跑 assumption-check 闸门 E 先验证稳定性 |
| deep_dossier 长文本无 canon 锁易被 LLM 章末覆盖破坏 | 落 discover 时用「只追加」校验 + 前端可视化对比新旧 dossier diff |
| 老 thread 兼容分支变成技术债，长期无法真正删字段 | 设定 sunset 时间点（如 6 个月后强制删除），期间在启动日志 warn 未迁移 thread 数量 |
| system_context 从 markdown 全档案改为渲染 entity_cards 后 token 数变化 | 落地前对当前一批 thread 打印新旧 system_context token 数对比，若激增 >30% 引入卡片截断策略 |
| 前端 EntityCardsEditor 现在无字段级校验友好度，deep_dossier 长文本编辑体验差 | 提供 FieldExpandDialog 放大编辑（复用现有组件） |

---

## 六、复用现有能力

**可直接复用**（避免重造）：
- `review_subgraph` — Phase 1 EntityCard 生成审核走通用 review 流程
- `VolumesReviewCards.tsx` — 参考其 JSON 卡片审核范式做 CharacterProfilesCards
- `parseEntityCardsJson` / `parseVolumesJson` — 参考 JSON 校验模式
- `EntityCardsEditor.tsx` — state 抽屉编辑复用（改 EntityCard 支持 deep_dossier）
- `_merge_cards` / `_apply_updates` — 章前建卡 / 章末动态更新的合流逻辑，扩展支持 deep_dossier
- `format_cards_for_chapter_prompt` — chapter_prompt 消费点已在用 entity_cards，无需改
- `format_equipment_for_context` — 装备渲染已从 entity_cards 消费

---

## 七、启动前的最后 checklist

动手前请依次确认：
- [ ] 已阅本文档 §一（背景）+ §二（4 个核心决策点）
- [ ] 决策 §2.1（deep_dossier vs 细粒度字段）
- [ ] 决策 §2.2（Phase 1 JSON 生成 vs markdown+解析）
- [ ] 决策 §2.4（老 state 迁移策略）
- [ ] 跑一次 assumption-check（闸门 E）：用 `docs/exec-plan-.../scripts/` 写个最小脚本让 LLM 从零出 EntityCard JSON 数组，观察 5 次输出稳定性
- [ ] 与用户对齐验收路径 §四
- [ ] 建立 `docs/exec-plan-yyyy-mm-dd_hh-mm-ss/` 目录，本文档转为 `original-plan.md`，跑 `execute-plan-plus` 分批推进
