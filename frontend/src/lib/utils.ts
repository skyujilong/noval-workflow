import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** 合并 className：clsx 处理条件类名，tailwind-merge 消解 Tailwind 冲突类。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
