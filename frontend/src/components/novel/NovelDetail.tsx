// 小说详情面板：展示当前 state 的关键进度（基础设定成果 + 章节进度 + 快照）。

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { reviewTypeLabel, type NovelState } from "../../lib/types";
import { EntityCardsReadonly } from "../state/EntityCardsReadonly";
import { PromoteCharacterPanel } from "../state/PromoteCharacterPanel";
import { usePromoteCharacter } from "../../hooks/usePromoteCharacter";

interface Props {
  state: NovelState;
  /** 当前小说 thread；提供时「次要角色」卡可提升为重要角色（带外写卡需要 thread 定位）。 */
  threadId?: string;
  /** 提升落库成功回调（父层应 refreshValues 刷新卡库）。 */
  onPromoted?: () => void | Promise<void>;
}

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div>
      <div className="mb-0.5 text-xs font-medium text-gray-500">{label}</div>
      <div className="prose prose-sm max-w-none max-h-48 overflow-y-auto rounded border border-gray-200 bg-white p-2">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
      </div>
    </div>
  );
}

export function NovelDetail({ state, threadId, onPromoted }: Props) {
  const titles = state.all_chapter_titles ?? [];
  // 提升会话状态机——hook 需无条件调用；threadId 缺省时不给卡片挂 onPromote（按钮不出现）。
  const promote = usePromoteCharacter(threadId ?? "", onPromoted ?? (() => {}));
  const canPromote = !!threadId;
  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-800">
          {state.novel_name || "（未命名）"}
        </h3>
        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
          已写 {state.total_chapters_written ?? 0} 章
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <Info label="类型" value={state.genre} />
        <Info label="风格" value={state.writing_style} />
        <Info label="读者" value={state.target_audience} />
        <Info label="基调" value={state.core_tone} />
        <Info label="每章字数" value={state.chapter_word_count} />
        <Info label="总字数" value={state.total_word_count} />
      </div>

      <Field label="核心主题" value={state.core_theme} />
      <Field label="世界观" value={state.world_building} />
      <Field label="力量体系" value={state.power_system} />
      <Field label="核心冲突" value={state.core_conflicts} />
      <Field label="整体大纲" value={state.overall_outline} />

      {/* 人物档案真源已并入 entity_cards（CharacterCard）——复用只读卡库视图整体展示，
          按 type 分组含人物/装备/物品/势力/地点，比原散文字段信息更完整。 */}
      {state.entity_cards?.length > 0 && (
        <div>
          <div className="mb-0.5 text-xs font-medium text-gray-500">人物档案 / 实体卡库</div>
          <EntityCardsReadonly
            cards={state.entity_cards}
            onPromote={canPromote ? promote.open : undefined}
          />
        </div>
      )}

      {/* 次要角色提升面板（受 promote.session 控制，null 时不渲染） */}
      <PromoteCharacterPanel ctl={promote} />


      <Field label="当前弧线大纲" value={state.current_arc_outline} />

      {/* 「当前草稿」只在草稿仍待审时展示（approved=false）。通过后 current_draft 会残留到下一个
          prepare_* 才被 reset_review_fields 清空，此窗口内落回详情会把刚确认的旧草稿又显示出来——
          用 !approved 拦掉「已通过的遗留草稿」，只保留真正 pending 的预览。 */}
      {state.review_type && state.current_draft && !state.approved && (
        <Field
          label={`当前草稿 · ${reviewTypeLabel(state.review_type)}`}
          value={state.current_draft}
        />
      )}

      {titles.length > 0 && (
        <div>
          <div className="mb-0.5 text-xs font-medium text-gray-500">
            章节标题（{titles.length}）
          </div>
          <ol className="list-inside list-decimal rounded border border-gray-200 bg-white p-2 text-sm text-gray-700">
            {titles.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded border border-gray-100 bg-gray-50 px-2 py-1">
      <div className="text-gray-400">{label}</div>
      <div className="truncate text-gray-700">{value || "—"}</div>
    </div>
  );
}
