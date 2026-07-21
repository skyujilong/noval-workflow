# 03-prepare-foundation

## Goal
迁移 7 个 foundation prepare 节点（core_theme/world_building/power_system/core_conflicts/overall_outline/character_cards/initial_status）到三层结构。设计通用 helper，供后续步骤复用。

## Depends on
- 01(render_user)、02(schema) 完成

## Do
1. 在 prompts/ 加 helper（放 render.py 或新 prompts/prepare_helpers.py）：
   ```python
   def build_prepare_result(state, *, review_type, task_contract, task, identity=None,
                            context_sections=None, snapshot_identity=False) -> dict
   ```
   - L1 system = build_system(identity or flavor.system_identity, task_contract)
   - L2 context = "\n\n".join(section bodies)
   - 返回 {system_prompt, context_prompt, task_prompt, review_type, **reset_review_fields()}
2. 各 prepare 改造（foundation.py:17-95）：
   - core_theme: identity=flavor.system_identity; L2=build_foundation_context(state, include_identity=False); L3=pack.core_theme_prompt（**注意 core_theme_prompt 内部已无 identity，P0 的 core_theme_request 是新方法，这里统一走 helper，可复用 core_theme_request 或直接内联**）。task_contract="为本小说创作核心主题与立意"
   - world_building/power_system/core_conflicts: 同上模式，task_contract 各异
   - overall_outline: L3=pack.overall_outline_prompt(...)；**删 base.py:overall_outline_prompt 开头的 system_identity 双注**（P1风险点）；task_contract="撰写全书战略概要"
   - character_cards: L3=pack.character_cards_prompt；**删 base.py:character_cards_prompt 开头 system_identity 双注**；task_contract="生成全套核心人物结构化卡"
   - initial_status: snapshot 类，identity=SNAPSHOT_IDENTITY_MAINTAINER；L2=build_foundation_context(state, exclude_snapshots=True, include_identity=False, deep_character_view=True)；L3=initial_status_prompt()；task_contract="固化人物初始基线（第0章）"
3. build_foundation_context：确认 include_identity=False 时不含身份（context.py:111-113 已是此逻辑，不动）。
4. 处理 P0 已建的 core_theme_request：本步统一用 helper 后，core_theme_request 可保留作验收用，或内联进 prepare。**保留 core_theme_request**（验收脚本依赖），prepare_core_theme 内部调它取三字段。

## Verify
1. `ruff check src/novel_workflow/prompts/render.py src/novel_workflow/nodes/foundation.py src/novel_workflow/prompts/base.py`
2. `mypy --strict` 上述文件
3. 扩展 scripts/verify_prompt_arch.py 加 7 个 foundation prepare 的检查（构造 mock state，跑各 prepare，打印三层，检查无双注/资料在L2/硬契约在L1）
4. `python scripts/verify_prompt_arch.py` 全 PASS
5. **不跑全量 pytest**（04-08 prepare 未改，generate 未改，预期红）

## Notes
- 执行结果：✅ 完成
- 改动文件：
  - render.py：加 build_prepare_fields helper（统一产出三字段）
  - foundation.py：7 个 prepare 全部改用 build_prepare_fields；initial_status 用 SNAPSHOT_IDENTITY_MAINTAINER
  - base.py：删 3 处 identity 双注（character_cards_prompt 的"## 角色定位"+identity、overall_outline_prompt 开头 identity、chapter_prompt 开头 identity）
  - verify_prompt_arch.py：加 run_prepare_checks 批量检查 7 个 foundation prepare
- 验证：ruff format+check 通过 / 验收脚本 8(core_theme) + 35(7 prepare × 5) = 43 项全 PASS
- 关键确认：每个 prepare 身份无双注（只在 L1）、资料血肉不在 L1（在 L2）、硬契约在 L1、三字段齐全
- 保留 core_theme_request（P0 产物）供验收，prepare_core_theme 走 build_prepare_fields 统一路径
- 预期红：subgraph/generate_summary/edit 子图引用 system_context 未改（06/04/05/07 修），本步不跑全量 pytest

