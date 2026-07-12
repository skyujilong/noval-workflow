// 提示词自进化抽屉：右侧抽屉，两页——「本书进化」（提炼人工打回→写进本书提示词）与
// 「题材整改库」（精炼入库 / 跨小说挑选导入）。作用域为单本小说（novelName），下一章生效。

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { EvolutionTab } from "./EvolutionTab";
import { DirectiveLibraryTab } from "./DirectiveLibraryTab";

type Tab = "evolve" | "library";

interface Props {
  open: boolean;
  novelName: string;
  genre: string;
  reviewType: string;
  /** 预填的来源修改要求（最近一次人工打回意见） */
  prefillFeedback: string;
  onClose: () => void;
}

export function PromptEvolutionModal({
  open,
  novelName,
  genre,
  reviewType,
  prefillFeedback,
  onClose,
}: Props) {
  const [tab, setTab] = useState<Tab>("evolve");

  // 每次打开回到「本书进化」页，避免残留上次的页签。
  useEffect(() => {
    if (open) setTab("evolve");
  }, [open]);

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0">
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>提示词进化 · {novelName || "未命名"}</SheetTitle>
          <SheetDescription>
            把人工打回意见提炼进本书提示词（下一章生效、可还原）；好的整改可精炼入题材整改库，供同题材小说复用。
          </SheetDescription>
        </SheetHeader>

        <div className="flex border-b text-sm">
          <TabButton active={tab === "evolve"} onClick={() => setTab("evolve")}>
            本书进化
          </TabButton>
          <TabButton active={tab === "library"} onClick={() => setTab("library")}>
            题材整改库
          </TabButton>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {tab === "evolve" ? (
            <EvolutionTab
              novelName={novelName}
              genre={genre}
              reviewType={reviewType}
              prefillFeedback={prefillFeedback}
              open={open && tab === "evolve"}
            />
          ) : (
            <DirectiveLibraryTab
              novelName={novelName}
              genre={genre}
              reviewType={reviewType}
              open={open && tab === "library"}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "flex-1 py-2 " +
        (active ? "border-b-2 border-blue-600 font-medium text-blue-600" : "text-gray-500")
      }
    >
      {children}
    </button>
  );
}
