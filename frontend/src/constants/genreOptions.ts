// 小说类型下拉选项。与后端 noval_workflow.prompts.registry.available_genres() 保持一致。
// 后端未匹配到任何题材包时会回退到"通用"包，因此旧线程的自定义 genre 值仍可运行。

export interface GenreOption {
  value: string;
  label: string;
}

export const GENRE_OPTIONS: GenreOption[] = [
  { value: "通用", label: "通用" },
  { value: "末日求生", label: "末日求生/灾变" },
  { value: "玄幻", label: "玄幻/仙侠" },
  { value: "都市", label: "都市" },
  { value: "科幻", label: "科幻" },
  { value: "两性情感", label: "两性情感" },
  { value: "搞笑异世界", label: "搞笑异世界" },
];
