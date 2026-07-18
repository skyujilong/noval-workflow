// 脑爆产物整合 review 面板：一次性展示 + 编辑 4 个正式设定字段 + 7 个全书基础参数。
//
// 渲染形态：静态右侧面板，与其他 interrupt 表单一致（不再用抽屉——interrupt 消费后
// 父层 InterruptHandler 会直接卸载本组件，抽屉的开关动画/受控 open 逻辑纯属画蛇添足，
// 反而带来「关闭动画期间又被打开一次」这类时序 bug）。
//
// 面板结构（顶→底）：
//   1. 全书基础参数（7 个短字段，用 <input>/<select> 直接填；genre 走下拉，其他走 text input）
//   2. 正式设定（4 个长字段，用 FieldBlock 双 tab：预览/编辑；力量体系视 has_power_system 显隐）
//   3. 按钮区：返回脑爆 / 保存并推进
//
// 必填校验：正式设定 3 项（core_theme / world_building / core_conflicts）+ 基础参数 4 项
//   （novel_name / genre / chapter_word_count / total_word_count）。写作风格 / 目标读者 /
//   核心基调允许空——build_foundation_context 会用占位文案兜底，不阻塞下游生成。
//
// resume 值为 dict（透传 langgraph Command(resume=...)）：
//   - 保存并推进 → { action: "advance", ...4 设定 + 7 基础字段 }
//     后端 brainstorm_extract_review 覆写 state 后路由到 collect_user_inputs
//   - 返回脑爆继续修改 → { action: "back_to_chat" }
//     后端复位 brainstorm_done、不写字段、路由回 brainstorm_chat
//
// has_power_system 由脑爆聊天页底部 switch 决定并已在结束脑爆前写回 state——本面板不再让用户
// 覆盖 flag，只按 payload.has_power_system 展示/隐藏力量体系编辑区。若用户结束脑爆后发现开关
// 选错，走「返回脑爆继续修改」回到聊天页调整 switch 即可。

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { GENRE_OPTIONS } from "@/constants/genreOptions";
import { fetchAvailableGenres } from "@/lib/langgraph";
import {
  buildBrainstormReviewAdvanceResume,
  buildBrainstormReviewBackResume,
  type BrainstormExtractReviewPayload,
  type BrainstormReviewResume,
} from "../../lib/interruptTypes";

// 首屏兜底：HTTP 请求返回前先用编译期 GENRE_OPTIONS 撑住渲染，接口拿到值后覆盖。
// 不再用 payload.allowed_genres——那个字段随 langgraph checkpoint 落盘，
// 老 thread 会锁死在旧快照上看不到新增题材（「搞笑异世界」漏进 review 面板的直接原因）。
const BOOTSTRAP_GENRES = GENRE_OPTIONS.map((opt) => opt.value);

interface Props {
  payload: BrainstormExtractReviewPayload;
  onSubmit: (value: BrainstormReviewResume) => void;
  disabled?: boolean;
}

export function BrainstormExtractReview({ payload, onSubmit, disabled }: Props) {
  // 4 设定字段初始值来自 payload；父层 InterruptHandler 用 payload.type 作 key，
  // 每个新 interrupt 都会重挂载本组件，useState 的初值即本次生命周期唯一值。
  const [coreTheme, setCoreTheme] = useState(payload.core_theme ?? "");
  const [worldBuilding, setWorldBuilding] = useState(payload.world_building ?? "");
  const [powerSystem, setPowerSystem] = useState(payload.power_system ?? "");
  const [coreConflicts, setCoreConflicts] = useState(payload.core_conflicts ?? "");
  // 7 基础字段初始值：后端 _extract_basic_fields 已预填（可能有值可能空），
  // 用户在本面板 review 时可保留 / 修改 / 主动清空
  const [novelName, setNovelName] = useState(payload.novel_name ?? "");
  const [genre, setGenre] = useState(payload.genre ?? "");
  const [writingStyle, setWritingStyle] = useState(payload.writing_style ?? "");
  const [targetAudience, setTargetAudience] = useState(payload.target_audience ?? "");
  const [coreTone, setCoreTone] = useState(payload.core_tone ?? "");
  const [chapterWordCount, setChapterWordCount] = useState(payload.chapter_word_count ?? "");
  const [totalWordCount, setTotalWordCount] = useState(payload.total_word_count ?? "");
  const [submitting, setSubmitting] = useState(false);

  // v2 保真度改造：finalize_confirm 节点纯 python 切分完整版 markdown 后，切不到内容的字段名
  // 累在 payload.missing_fields 里。前端把这份 Set 化便于各 FieldBlock O(1) 判断，
  // 命中的字段头部渲染黄色警告条提示用户手填或返回聊天补充。
  const missing = new Set(payload.missing_fields ?? []);

  // genre 下拉候选：挂载时从 HTTP GET /genres 拉，绕过 checkpoint 快照。
  // 首屏用 BOOTSTRAP_GENRES 撑住渲染避免闪空。请求失败保留 bootstrap 值，不 crash。
  const [genreOptions, setGenreOptions] = useState<string[]>(BOOTSTRAP_GENRES);
  useEffect(() => {
    let cancelled = false;
    fetchAvailableGenres()
      .then((genres) => {
        if (!cancelled && genres.length > 0) setGenreOptions(genres);
      })
      .catch((err) => {
        // 拉不到就用 bootstrap 值继续渲染，控制台留一行方便排查
        console.warn("[BrainstormExtractReview] fetchAvailableGenres 失败,继续使用 bootstrap:", err);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 必填校验：3 设定 + 4 基础参数（写作风格/目标读者/核心基调允许空，下游有占位兜底）
  const canAdvance =
    coreTheme.trim().length > 0 &&
    worldBuilding.trim().length > 0 &&
    coreConflicts.trim().length > 0 &&
    novelName.trim().length > 0 &&
    genre.trim().length > 0 &&
    chapterWordCount.trim().length > 0 &&
    totalWordCount.trim().length > 0;

  const isDisabled = disabled || submitting;

  const handleAdvance = () => {
    if (!canAdvance) return;
    setSubmitting(true);
    onSubmit(
      buildBrainstormReviewAdvanceResume({
        core_theme: coreTheme,
        world_building: worldBuilding,
        power_system: payload.has_power_system ? powerSystem : undefined,
        core_conflicts: coreConflicts,
        novel_name: novelName,
        genre,
        writing_style: writingStyle,
        target_audience: targetAudience,
        core_tone: coreTone,
        chapter_word_count: chapterWordCount,
        total_word_count: totalWordCount,
      })
    );
  };

  const handleBackToChat = () => {
    setSubmitting(true);
    onSubmit(buildBrainstormReviewBackResume());
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-gray-800">脑爆产物 · 整合 Review</h3>
        <p className="mt-1 text-sm text-gray-500">{payload.message}</p>
      </div>

      {/* 全书基础参数区：7 个短字段，AI 已从脑爆对话预填，用户可 review 修改 */}
      <section className="rounded border border-gray-200 bg-gray-50/50 p-3">
        <h4 className="mb-2 text-sm font-semibold text-gray-800">
          全书基础参数
          <span className="ml-2 text-xs font-normal text-gray-500">
            （AI 已从脑爆对话预填，可修改或补充；带 * 为必填）
          </span>
        </h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <BasicInput
            label="小说名称"
            value={novelName}
            onChange={setNovelName}
            disabled={isDisabled}
            required
            placeholder="如：星际迷途、长安风云"
          />
          <BasicSelect
            label="小说类型"
            value={genre}
            onChange={setGenre}
            disabled={isDisabled}
            required
            options={genreOptions}
          />
          <BasicInput
            label="写作风格"
            value={writingStyle}
            onChange={setWritingStyle}
            disabled={isDisabled}
            placeholder="如：硬核、意识流、白描、细腻内省"
          />
          <BasicInput
            label="目标读者"
            value={targetAudience}
            onChange={setTargetAudience}
            disabled={isDisabled}
            placeholder="如：青少年男性、职场女性"
          />
          <BasicInput
            label="核心基调"
            value={coreTone}
            onChange={setCoreTone}
            disabled={isDisabled}
            placeholder="如：热血励志、温情治愈、悬疑压抑"
          />
          <BasicInput
            label="每章字数"
            value={chapterWordCount}
            onChange={setChapterWordCount}
            disabled={isDisabled}
            required
            placeholder="如：3000字、5000字"
          />
          <BasicInput
            label="总字数目标"
            value={totalWordCount}
            onChange={setTotalWordCount}
            disabled={isDisabled}
            required
            placeholder="如：30万字、100万字"
          />
        </div>
      </section>

      {/* 正式设定区：4 个长字段（力量体系视 has_power_system 显隐），保留原有 FieldBlock 双 tab */}
      <div className="space-y-5">
        <FieldBlock
          label="核心主题与立意"
          value={coreTheme}
          onChange={setCoreTheme}
          disabled={isDisabled}
          required
          missing={missing.has("core_theme")}
        />
        <FieldBlock
          label="世界观设定"
          value={worldBuilding}
          onChange={setWorldBuilding}
          disabled={isDisabled}
          required
          missing={missing.has("world_building")}
        />
        {payload.has_power_system && (
          <FieldBlock
            label="力量体系"
            value={powerSystem}
            onChange={setPowerSystem}
            disabled={isDisabled}
            missing={missing.has("power_system")}
            // 力量体系视聊天页开关可选，不做必填校验
          />
        )}
        <FieldBlock
          label="核心冲突"
          value={coreConflicts}
          onChange={setCoreConflicts}
          disabled={isDisabled}
          required
          missing={missing.has("core_conflicts")}
        />
      </div>

      <div className="flex flex-col items-stretch gap-2 border-t pt-4 sm:flex-row sm:items-center">
        <div className="mr-auto text-xs text-gray-400">
          {canAdvance ? "" : "请补齐必填的基础参数与正式设定后再推进"}
        </div>
        <Button variant="ghost" onClick={handleBackToChat} disabled={isDisabled}>
          返回脑爆继续修改
        </Button>
        <Button onClick={handleAdvance} disabled={isDisabled || !canAdvance}>
          {submitting ? "⏳ 提交中…" : "保存并推进"}
        </Button>
      </div>
    </div>
  );
}

// 基础参数专用短文本输入：单行 input，label 在左、input 在右
interface BasicInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  required?: boolean;
  placeholder?: string;
}

function BasicInput({ label, value, onChange, disabled, required, placeholder }: BasicInputProps) {
  const showEmpty = required && !value.trim();
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-1 text-xs font-medium text-gray-700">
        <span>{label}</span>
        {required && <span className="text-red-500">*</span>}
        {showEmpty && <span className="text-amber-600">（必填）</span>}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
      />
    </div>
  );
}

// 基础参数专用下拉：genre 用（六选一 + 空选项让用户显式选未定）
interface BasicSelectProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  required?: boolean;
  options: string[];
}

function BasicSelect({ label, value, onChange, disabled, required, options }: BasicSelectProps) {
  const showEmpty = required && !value.trim();
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-1 text-xs font-medium text-gray-700">
        <span>{label}</span>
        {required && <span className="text-red-500">*</span>}
        {showEmpty && <span className="text-amber-600">（必填）</span>}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
      >
        <option value="">（请选择）</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}

interface FieldBlockProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  required?: boolean;
  /** v2 保真度改造：完整版 markdown 里没切到本节 → 头部渲染黄色警告条提示用户手填或返回聊天。 */
  missing?: boolean;
}

// 单字段的预览/编辑双 tab 容器：初值有内容 → 预览态可视化确认；空且必填 → 编辑态便于立即补录。
// 预览用 react-markdown + remark-gfm 渲染，力量体系 LLM 输出的 GFM 表格能真表格显示。
function FieldBlock({ label, value, onChange, disabled, required, missing }: FieldBlockProps) {
  // 初始 mode 派生：字段有内容且非仅空白 → 预览；否则编辑。用户切换后靠自己 useState 记忆。
  // missing=true 时（切分失败）也强制落到编辑态，方便用户第一眼就能补录。
  const [mode, setMode] = useState<"preview" | "edit">(() =>
    value.trim().length > 0 && !missing ? "preview" : "edit"
  );
  const showEmpty = required && !value.trim();

  return (
    <div className="space-y-1.5">
      {missing && (
        <div className="rounded border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">
          ⚠️ AI 整理的完整版里没找到这一节，请手填或返回聊天补充
        </div>
      )}
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-gray-800">{label}</label>
        {required && <span className="text-xs text-red-500">*</span>}
        {showEmpty && <span className="text-xs text-amber-600">（必填）</span>}
        <div className="ml-auto inline-flex overflow-hidden rounded border border-gray-300 text-xs">
          <button
            type="button"
            onClick={() => setMode("preview")}
            className={`px-2 py-0.5 transition ${
              mode === "preview"
                ? "bg-blue-500 text-white"
                : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            预览
          </button>
          <button
            type="button"
            onClick={() => setMode("edit")}
            className={`border-l border-gray-300 px-2 py-0.5 transition ${
              mode === "edit"
                ? "bg-blue-500 text-white"
                : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            编辑
          </button>
        </div>
      </div>
      {mode === "preview" ? (
        // prose 类由 @tailwindcss/typography 提供表格边框/间距样式；max-h + overflow-y-auto 防超长
        <div className="prose prose-sm max-w-none max-h-96 overflow-y-auto rounded border border-gray-200 bg-white p-3">
          {value.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
          ) : (
            <div className="text-sm italic text-gray-400">（暂无内容，切到「编辑」填写）</div>
          )}
        </div>
      ) : (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          rows={12}
          className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm leading-relaxed focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}
    </div>
  );
}
