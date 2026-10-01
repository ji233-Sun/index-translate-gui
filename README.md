# Index Translate Studio

用 Tauri 2、Vue 3 和 Element Plus 构建的 Index-Translate 本地桌面客户端。提供模型多源下载、本地部署、翻译体验，以及 OpenAI / Anthropic 文本 API。非哔哩哔哩官方客户端。

## 功能

- **模型工作台**：Index-Translate 2B、9B、35B-A3B Preview；仅聚焦通用文本翻译。
- **下载管理**：ModelScope、Hugging Face、HF Mirror、自定义 HTTPS HF 镜像；暂停、断点续传、进度、速度、失败重试、磁盘空间检查与哈希校验。
- **本地部署**：安装推理依赖、启动/停止模型；自动选择 CUDA → Apple MPS → CPU，也可手动选择。退出桌面应用会回收 Python 工作进程。
- **翻译体验**：官方格式的翻译提示、语言选择、自定义语言名称、额外翻译要求、流式显示、停止生成与复制译文。
- **API 接入**：`/v1/chat/completions`、`/v1/completions`、`/v1/responses`、`/v1/messages`，支持文本流式与非流式请求、真实 token 用量、`/v1/models`。
- **偏好设置**：端口、访问密钥、局域网访问、模型目录、下载源、计算设备、上下文与输出预算。

## 内嵌 Python

Windows x64、macOS Apple Silicon 和 Linux x64 安装包均包含 **Python 3.12.12 + uv 0.10.9 + 基础管理依赖**。最终用户无需安装 Python、Node.js 或 Rust，首次打开应用不需要联网安装 Python。

构建脚本通过 uv 获取 python-build-standalone 解释器，基础管理依赖按 `backend/uv.lock` 安装到打包副本中。运行时用内嵌解释器创建应用专属虚拟环境，继承该打包副本的基础依赖。首次点击「安装推理依赖」时，通过 uv 安装 PyTorch、Transformers 和 Accelerate；模型权重单独按所选来源下载。两者均需要网络，并占用额外磁盘空间。系统 Python 和全局包不会被修改。

PyTorch 安装采用 `uv pip --torch-backend auto`，CUDA 是否可用取决于驱动及对应 wheel。依赖安装使用 PyPI / PyTorch 的分发地址，与模型下载源设置独立。

## 本地开发

需要 Node.js 22.12+、Rust stable 及 [Tauri 对应平台系统依赖](https://v2.tauri.app/start/prerequisites/)。后端测试使用 uv。

```sh
npm install
npm run desktop
```

`desktop` 会先下载并准备当前平台的内嵌运行时，再启动 Vite 与 Tauri。准备阶段只写入项目内的 `src-tauri/python`、`src-tauri/binaries`，不会注册或覆盖系统 Python。内嵌运行时与构建产物已加入 `.gitignore`。

仅预览界面：

```sh
npm run dev
```

打开 `http://127.0.0.1:1420`。浏览器预览明确标识为预览，不能下载、部署或翻译，也不会伪造模型运行状态或翻译结果。

## 使用顺序

1. 在「模型工作台」选择下载来源。国内网络优先尝试 ModelScope 或 HF Mirror。
2. 首次使用推荐 2B。点击「下载模型」，下载进度会实时更新；暂停或网络中断保留已下载内容。
3. 点击「安装推理依赖」，在运行日志中查看安装状态。
4. 权重下载和依赖安装完成后，点击「启动模型」。等待状态变为运行中。
5. 打开「翻译体验」，或者从「API 接入」复制连接信息到第三方应用。

修改端口、密钥、计算设备或存储位置前，先停止模型和下载。更换存储目录不会自动移动已有文件；选回原目录后会重新识别模型。关闭应用后模型停止，未完成下载可再次点击继续。

## 模型及硬件

| 模型 | 当前权重规模 | 硬件说明 |
| --- | --- | --- |
| 2B | 约 4.55 GB，另有 tokenizer 等文件 | 官方 CUDA BF16 参考约 8 GB；本客户端 CPU/MPS FP32 建议 16 GB 内存 |
| 9B | 约 19.31 GB，另有 tokenizer 等文件 | 官方 CUDA BF16 参考约 24 GB；本客户端 CPU/MPS FP32 建议 48 GB 内存 |
| 35B-A3B Preview | 下载前查询完整文件清单 | 35B 总参数、3B 激活参数；仍需要存放全部权重，不能按 3B 估算内存 |

内存建议不是保证值，系统占用、上下文及框架缓冲区都会影响实际需求。CUDA 使用 BF16（不支持时 FP16），CPU / MPS 使用 FP32，兼容性优先。默认上下文 4096、输出上限 1024；超限请求返回明确错误。当前实现通过 Transformers 加载原始 Safetensors，不包含 GGUF、量化或 vLLM 服务。

截至 2026-10-01 核验，35B Preview 的 HF / ModelScope 文件清单只有配置和权重索引，缺少实际权重分片。应用保留该模型选项，但会实时校验上游清单，缺权重时阻止下载完成和部署。正式仓库 ID 为 `IndexTeam/Index-Translate-35B-A3B-preview`，不使用旧的无 `-preview` 链接。

## API 兼容范围

默认地址 `http://127.0.0.1:8765`，密钥由首次启动随机生成。OpenAI 客户端 Base URL 为 `http://127.0.0.1:8765/v1`，Anthropic 客户端 Base URL 为 `http://127.0.0.1:8765`。

| 路由 | 鉴权 | 输入 |
| --- | --- | --- |
| `GET /v1/models` | `Authorization: Bearer <key>` | 返回当前已加载模型 |
| `POST /v1/chat/completions` | Bearer | 文本 `messages`，可含 system / developer / user / assistant |
| `POST /v1/completions` | Bearer | 单个字符串 `prompt`，用于传统 Completion 客户端 |
| `POST /v1/responses` | Bearer | 字符串 `input` 或文本消息数组，`instructions`，`store: false` |
| `POST /v1/messages` | `x-api-key` 或 Bearer | 文本 `messages`，顶层 `system`，必填 `max_tokens` |
| `GET /health` | 无 | 只返回服务就绪状态 |

支持 `stream`、`temperature`、`top_p`、输出预算和最多四个停止字符串。Chat Completions 可通过 `stream_options.include_usage` 获取末尾用量事件；Responses 和 Messages 输出对应的 SSE 事件序列。模型一次处理一个请求，忙碌时返回 429。真实 token 统计来源于模型 tokenizer / 生成结果，不按字符估算。

这是面向**文本翻译**的兼容实现，不是通用 Agent 服务。不支持工具调用、图片/音频、结构化 JSON 输出、批量 completions、logprobs、Responses 历史存储/检索、后台任务、`previous_response_id` 或推理模式。显式请求这些功能会返回错误。模型输出仍取决于提示内容；外部接口不会擅自把普通聊天输入改写成翻译指令。

```sh
# 从 GUI 的 API 接入页复制访问密钥，替换下面的示例值。
export INDEX_API_KEY='your-local-key'
curl -N http://127.0.0.1:8765/v1/chat/completions \
  -H "Authorization: Bearer $INDEX_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"IndexTeam/Index-Translate-2B","stream":true,"max_tokens":256,"messages":[{"role":"user","content":"请将以下文本翻译为英语，直接输出翻译结果，不要进行任何解释。\n\n你好，世界。"}]}'
```

管理接口仅绑定随机本机端口，使用独立随机控制密钥，并由 Rust IPC 代理；不会通过公开 API 暴露设置或安装能力。公网部署不在本项目范围内。局域网开关开启后使用明文 HTTP，应限制在可信网络内。

## 架构与文件

```text
Vue 3 + Element Plus
  └─ Tauri IPC（Rust，限定管理操作）
      └─ 内嵌 Python → 应用虚拟环境
          ├─ 本机控制服务：设置、下载、日志、启停、翻译体验
          ├─ Transformers：本地 Safetensors，禁止远程代码，关闭 thinking
          └─ 公开 API 服务：可配置监听地址、端口、访问密钥
```

- `src/`：四个页面、类型及桌面服务连接。
- `src-tauri/`：Tauri 配置、Rust 进程管理、应用图标。
- `backend/studio/`：下载源适配、续传与哈希校验、模型加载、API 协议转换、设置和管理接口。
- `backend/tests/`：不下载大模型的协议、下载与状态管理回归测试。
- `scripts/prepare-sidecar.mjs`：准备内嵌 uv/Python，校验 uv 下载哈希，安装基础依赖。
- `.github/workflows/ci.yml`：前端/服务校验及三平台安装包构建。

应用数据目录由 Tauri 的 `app_data_dir` 决定，例如 macOS `~/Library/Application Support/com.indextranslate.studio`。包含设置、虚拟环境及默认模型目录。设置按临时文件原子替换保存，POSIX 文件权限为 0600。模型下载固定到源内容版本，检查 SHA-256 或 Git blob SHA-1；只有全部权重与配置校验完成才标记为就绪。

## 检查与构建

```sh
npm run build
uv sync --project backend --frozen
npm run check:backend
npm run test:backend
npm run prepare:sidecar
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo clippy --manifest-path src-tauri/Cargo.toml --locked -- -D warnings
npm run desktop:build
```

CI 在 push、pull request 或手动触发时执行。先运行前端构建、Ruff 与 pytest，再构建 macOS Apple Silicon、Windows x64、Linux x64 安装包，作为 Actions Artifacts 保留 14 天。不创建 GitHub Release，不上传模型权重。Windows/macOS 签名与 Apple 公证需要项目持有人的证书；当前流水线生成未签名构建。

macOS Intel 暂未列入构建矩阵，当前 Qwen3.5 所需的新版 PyTorch 不提供对应 Intel macOS 官方 wheel。Windows/Linux CUDA 与 MPS 实际推理应分别在目标硬件验证。自动化测试用受控生成器替代神经网络计算，只证明协议、控制逻辑和下载行为，不代表真实模型质量或性能。

## 上游资料

- [Index-Translate 仓库](https://github.com/bilibili/Index-Translate)
- [官方文本推理说明](https://github.com/bilibili/Index-Translate/tree/main/inference/llm)
- [Hugging Face 模型合集](https://huggingface.co/collections/IndexTeam/index-translate)
- [ModelScope 2B](https://modelscope.cn/models/IndexTeam/Index-Translate-2B)
- [ModelScope 35B Preview](https://modelscope.cn/models/IndexTeam/Index-Translate-35B-A3B-preview)
- [Tauri 构建文档](https://v2.tauri.app/distribute/pipelines/github/)

模型及 Python、uv、PyTorch 等依赖分别遵循各自许可证；内嵌解释器和包中的许可证文件随资源一同分发。
