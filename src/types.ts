import catalog from "../backend/studio/models.json";

export type Page = "models" | "translate" | "api" | "settings";
export type Source = "modelscope" | "huggingface" | "hf-mirror" | "custom";
export interface Settings {
  port: number;
  host: "127.0.0.1" | "0.0.0.0";
  api_key: string;
  model_dir: string;
  source: Source;
  mirror_url: string;
  python_index_url: string;
  torch_auto_backend: boolean;
  device: "auto" | "cpu" | "mps" | "cuda";
  max_context: number;
  max_tokens: number;
}
export interface Model {
  id: string;
  name: string;
  size: string;
  repo: string;
  weight_gb: number | null;
  memory: string;
  description: string;
  badge: string;
  local: {
    status: "missing" | "partial" | "ready";
    downloaded: number;
    total: number;
    source?: Source;
  };
}
export interface Snapshot {
  models: Model[];
  settings: Settings;
  runtime: { status: string; error: string };
  deployment: {
    status: string;
    model_id: string;
    error: string;
    since: number | null;
  };
  download: {
    status: string;
    model_id: string;
    downloaded: number;
    total: number;
    speed: number;
    file: string;
    error: string;
  };
  translation: {
    status: string;
    text: string;
    error: string;
    elapsed: number;
    output_tokens: number;
  };
  hardware: {
    platform: string;
    arch: string;
    memory_total: number;
    memory_available: number;
    disk_free: number;
    device: string;
  };
  stats: { requests: number; tokens_per_second: number; busy: boolean };
  logs: { time: number; level: string; message: string }[];
}
export type Action = (
  path: string,
  body?: unknown,
  method?: string,
  message?: string,
) => Promise<boolean>;

export const sources: { value: Source; label: string; hint: string }[] = [
  { value: "modelscope", label: "ModelScope", hint: "国内优先" },
  { value: "huggingface", label: "Hugging Face", hint: "官方源" },
  { value: "hf-mirror", label: "HF Mirror", hint: "国内镜像" },
  { value: "custom", label: "自定义 HF 镜像", hint: "HTTPS" },
];
export const pythonSources = [
  { value: "https://pypi.org/simple", label: "PyPI 官方源" },
  { value: "https://pypi.tuna.tsinghua.edu.cn/simple", label: "清华大学 TUNA" },
  { value: "https://mirrors.aliyun.com/pypi/simple", label: "阿里云镜像" },
];
export function bytes(value: number) {
  if (!value) return "0 B";
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 3);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${["B", "KB", "MB", "GB"][index]}`;
}

// 浏览器预览只展示目录信息，不模拟下载、硬件、翻译结果或运行状态。
export function initialSnapshot(): Snapshot {
  const local = () => ({ status: "missing" as const, downloaded: 0, total: 0 });
  return {
    models: catalog.map((model) => ({ ...model, local: local() })),
    settings: {
      port: 8765,
      host: "127.0.0.1",
      api_key: "",
      model_dir: "",
      source: "modelscope",
      mirror_url: "https://hf-mirror.com",
      python_index_url: "https://pypi.org/simple",
      torch_auto_backend: true,
      device: "auto",
      max_context: 4096,
      max_tokens: 1024,
    },
    runtime: { status: "unknown", error: "" },
    deployment: { status: "stopped", model_id: "", error: "", since: null },
    download: {
      status: "idle",
      model_id: "",
      downloaded: 0,
      total: 0,
      speed: 0,
      file: "",
      error: "",
    },
    translation: {
      status: "idle",
      text: "",
      error: "",
      elapsed: 0,
      output_tokens: 0,
    },
    hardware: {
      platform: "",
      arch: "",
      memory_total: 0,
      memory_available: 0,
      disk_free: 0,
      device: "",
    },
    stats: { requests: 0, tokens_per_second: 0, busy: false },
    logs: [],
  };
}
