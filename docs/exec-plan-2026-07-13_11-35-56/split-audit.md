# Split audit

## Coverage map

| Original requirement | Step(s) | Status |
| --- | --- | --- |
| interrupt_types.py 加 3 枚举 + 映射 | 01-contracts-backend | covered |
| interruptTypes.ts 镜像 + TYPE_TO_FORM + DIRECTION_TITLE | 02-contracts-frontend | covered |
| types.ts REVIEW_TYPE_LABELS 加中文 | 02-contracts-frontend | covered |
| 新建 prompts/character_profiles_discover.py（生成 + 审核 prompt + 组装函数） | 03-prompts | covered |
| prompts/__init__.py re-export | 03-prompts | covered |
| subgraph.py imports + _HISTORY_MAX_ROUNDS + _REGEN_OUTPUT_HINTS + _REVIEW_PROMPTS | 04-subgraph-registry | covered |
| 新建 nodes/character_profiles_discover.py（prepare + save） | 05-nodes | covered |
| 新建 character_profiles_discover_subgraph.py（SubState + make_edit_step_subgraph 工厂调用） | 06-subgraph-wire | covered |
| graph.py imports + add_node + 拆边（generate_summary → discover → chapter_edit） | 07-graph-wire | covered |
| 新建 tests/unit_tests/test_character_profiles_discover.py | 08-tests | covered |
| 端到端手动 + 全套 pytest + 前端 tsc | 09-final-verify | covered |

## Ordering rationale

契约优先（前后端 InterruptType 值字符串必须一字不差，否则前端落 unknown）→ 依赖契约的注册表与 prompt 常量 → 消费 prompt 的节点 → 编排节点的子图 → 挂载到父图。

- 01/02 契约在最前，两边同步一次即锁定 wire。
- 03 prompt 先于 04 registry：subgraph.py 要 import prompt 常量。
- 04 registry 先于 05 nodes：nodes 里 review_type 字符串要落到 registry 里才有意义。
- 05 nodes 先于 06 subgraph：subgraph 工厂 import prepare/save 闭包。
- 06 subgraph 先于 07 graph：graph.py import `character_profiles_discover_step`。
- 08 tests 在实现全部就位后跑，避免中途 import 断裂噪声。
- 09 final-verify 端到端。

## Fixes made during audit

- 无 state.py 修改（决策 1：字段类型不变、无锚定字段），未列入 step。
- consistency.py / save_character_profiles / evolution 均已在 plan 里显式声明"不做"，不列 step。

## Result

No known omissions. Step order follows build dependencies.
