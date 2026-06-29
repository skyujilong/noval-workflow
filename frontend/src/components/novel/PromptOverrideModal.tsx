// 按小说的提示词覆盖抽屉：用题材默认值预填每个编辑框，仅保存与默认不同的字段。
// 字段较多，故用右侧抽屉（占满视口高度、内容区纵向滚动），头/脚固定。
// 始终提供「还原默认」，防止改崩。存储不入 langgraph state，改完即时生效、对历史回放也生效。

import { useCallback, useEffect, useState } from "react";
import {
  getPromptOverrides,
  savePromptOverrides,
} from "../../lib/langgraph";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  open: boolean;
  novelName: string;
  genre: string;
  onClose: () => void;
}

// GenreFlavor 可覆盖字段：key 与后端 dataclass 字段一一对应；long 决定文本框高度。
const FIELDS: { key: string; label: string; long: boolean }[] = [
  { key: "system_identity", label: "系统身份描述", long: true },
  { key: "chapter_style_rules", label: "章节文体风格", long: true },
  { key: "chapter_example", label: "风格示例（❌/✅ 对照）", long: true },
  { key: "chapter_review_checklist", label: "章节审核·文风检查清单", long: true },
  { key: "core_theme_focus", label: "核心主题·题材聚焦", long: false },
  { key: "world_building_focus", label: "世界观·题材聚焦", long: false },
  { key: "core_conflicts_focus", label: "核心冲突·题材聚焦", long: false },
  { key: "character_profiles_focus", label: "角色档案·题材聚焦", long: false },
  { key: "overall_outline_focus", label: "总大纲·题材聚焦", long: false },
  { key: "titles_focus", label: "标题·题材聚焦", long: false },
  { key: "arc_focus", label: "弧线大纲·题材聚焦", long: false },
];

export function PromptOverrideModal({ open, novelName, genre, onClose }: Props) {
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 打开时拉取题材默认值 + 已存覆盖，初始化每个编辑框（覆盖优先，否则默认）。
  useEffect(() => {
    if (!open || !novelName) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPromptOverrides(novelName, genre)
      .then((res) => {
        if (cancelled) return;
        setDefaults(res.defaults ?? {});
        const init: Record<string, string> = {};
        for (const f of FIELDS) {
          init[f.key] = res.overrides?.[f.key] ?? res.defaults?.[f.key] ?? "";
        }
        setValues(init);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, novelName, genre]);

  const setField = useCallback((key: string, val: string) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  }, []);

  const restoreField = useCallback(
    (key: string) => {
      setValues((prev) => ({ ...prev, [key]: defaults[key] ?? "" }));
    },
    [defaults]
  );

  const restoreAll = useCallback(() => {
    const reset: Record<string, string> = {};
    for (const f of FIELDS) reset[f.key] = defaults[f.key] ?? "";
    setValues(reset);
  }, [defaults]);

  const handleSave = useCallback(async () => {
    // 仅提交「非空且与默认不同」的字段；其余回退题材默认。
    const out: Record<string, string> = {};
    for (const f of FIELDS) {
      const v = (values[f.key] ?? "").trim();
      const d = (defaults[f.key] ?? "").trim();
      if (v && v !== d) out[f.key] = values[f.key];
    }
    setSaving(true);
    setError(null);
    try {
      await savePromptOverrides(novelName, out);
      onClose();
    } catch (e: unknown) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setSaving(false);
    }
  }, [values, defaults, novelName, onClose]);

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-xl"
      >
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>提示词配置 · {novelName || "未命名"}</SheetTitle>
          <SheetDescription>
            题材【{genre || "通用"}】默认提示词已预填。仅保存与默认不同的内容；留空或点「还原」即用默认。
            修改即时生效，对该小说后续生成（含历史回放）均生效。
          </SheetDescription>
        </SheetHeader>

        {error && (
          <div className="mx-6 mt-4 rounded bg-red-50 p-2 text-xs text-red-600">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex-1 py-10 text-center text-sm text-gray-400">
            加载中…
          </div>
        ) : (
          <div className="flex-1 space-y-4 overflow-y-auto px-6 py-4">
            {FIELDS.map((f) => {
              const isCustom =
                (values[f.key] ?? "").trim() !== (defaults[f.key] ?? "").trim() &&
                (values[f.key] ?? "").trim() !== "";
              return (
                <div key={f.key}>
                  <div className="mb-1 flex items-center justify-between">
                    <Label className="text-gray-700">
                      {f.label}
                      {isCustom && (
                        <span className="ml-2 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-normal text-blue-600">
                          已自定义
                        </span>
                      )}
                    </Label>
                    <button
                      type="button"
                      onClick={() => restoreField(f.key)}
                      className="text-xs text-gray-400 hover:text-blue-600"
                    >
                      还原
                    </button>
                  </div>
                  <Textarea
                    value={values[f.key] ?? ""}
                    onChange={(e) => setField(f.key, e.target.value)}
                    rows={f.long ? 8 : 3}
                    className="font-mono text-xs"
                  />
                </div>
              );
            })}
          </div>
        )}

        <SheetFooter className="gap-2 border-t px-6 py-4 sm:gap-2">
          <Button
            variant="outline"
            onClick={restoreAll}
            disabled={loading || saving}
            className="mr-auto"
          >
            全部还原默认
          </Button>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={loading || saving}>
            {saving ? "保存中…" : "保存"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
