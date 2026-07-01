// 单字段「放大」编辑：占满视口的大编辑框，专注编辑一个长文本字段（世界观/大纲/草稿等）。
// 编辑的是与抽屉共享的同一份草稿（onChange 直接写回），关闭即保留，无需额外同步。

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  open: boolean;
  title: string;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  onClose: () => void;
}

export function FieldExpandDialog({ open, title, value, disabled, onChange, onClose }: Props) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="flex h-[86vh] max-h-[86vh] w-[92vw] max-w-[1100px] flex-col gap-3">
        <DialogHeader>
          <DialogTitle>编辑 · {title}</DialogTitle>
          <DialogDescription>
            编辑完点「完成」返回；改动会保留在编辑面板里，需再点面板的「保存」才写入。
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={value}
          disabled={disabled}
          autoFocus
          onChange={(e) => onChange(e.target.value)}
          className="min-h-0 flex-1 resize-none text-sm leading-relaxed"
        />
        <div className="flex justify-end">
          <Button onClick={onClose}>完成</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
