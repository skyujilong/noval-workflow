// 分卷规划(volumes) 的结构化 JSON 源码编辑器——「编辑当前状态」抽屉里的可编辑入口(与只读观测区 VolumesReadonly 配套)。
//
// 数据量小(≤5 卷) + 字段固定 + 硬约束多(拼接规则/range 大小),JSON 源码直改比逐字段控件
// 更快也更透明。校验逻辑在 lib/editableState.ts::parseVolumesJson,与后端 save_volumes 对齐;
// 非法时父层(useStateEditor.volumesError) 禁止保存。解析成功即用 VolumesReadonly 预览
// 「保存后长什么样」,让用户直观确认落地形态。
//
// 手改安全性:volumes 覆盖语义(无 reducer),除非滚动生成卷(save_volumes)才被程序更新;
// 普通节点执行不触碰,故手改安全。

import { Textarea } from "@/components/ui/textarea";
import { parseVolumesJson } from "../../lib/editableState";
import { VolumesReadonly } from "./VolumesReadonly";

interface Props {
  /** JSON 源码草稿(受控) */
  value: string;
  /** 校验错误(null = 合法)——来自 useStateEditor.volumesError */
  error: string | null;
  /** run 进行中 / 后台忙:只读展示,不可编辑 */
  disabled: boolean;
  onChange: (value: string) => void;
}

export function VolumesEditor({ value, error, disabled, onChange }: Props) {
  // 解析成功时用只读面板预览「保存后长什么样」;失败时预览区让位给错误提示。
  const parsed = parseVolumesJson(value);

  return (
    <div className="space-y-2">
      <Textarea
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        rows={14}
        spellCheck={false}
        className="font-mono text-xs"
        placeholder='[{"index":1,"title":"第一卷·少年入宗","summary":"…","setup_for_next":"…","chapter_start":1,"planned_end":28,"actual_end":null,"status":"in_progress"}]'
      />
      {error ? (
        <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-600">
          ⚠ {error}
        </div>
      ) : (
        <div className="rounded border border-gray-100 bg-white p-2">
          <div className="mb-1 text-[10px] text-gray-400">保存后预览(结构化)</div>
          <VolumesReadonly volumes={parsed.value ?? []} />
        </div>
      )}
    </div>
  );
}
