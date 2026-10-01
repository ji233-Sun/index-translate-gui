<script setup lang="ts">
import { computed } from "vue";
import {
  Download,
  VideoPlay,
  VideoPause,
  Cpu,
  ArrowRight,
  CircleCheckFilled,
  FolderOpened,
  Loading,
  Connection,
} from "@element-plus/icons-vue";
import {
  bytes,
  sources,
  type Action,
  type Page,
  type Snapshot,
  type Source,
  type Model,
} from "../types";

const props = defineProps<{
  state: Snapshot;
  action: Action;
  pending: string;
  desktop: boolean;
}>();
const emit = defineEmits<{ navigate: [page: Page]; logs: [] }>();
const activeDownload = computed(() =>
  ["preparing", "downloading", "pausing"].includes(props.state.download.status),
);
const deployed = computed(() =>
  ["running", "loading", "stopping"].includes(props.state.deployment.status),
);
const readyCount = computed(
  () =>
    props.state.models.filter((model) => model.local.status === "ready").length,
);
const percent = computed(() =>
  Math.min(
    100,
    props.state.download.total
      ? (props.state.download.downloaded / props.state.download.total) * 100
      : 0,
  ),
);
const activeName = computed(
  () =>
    props.state.models.find((m) => m.id === props.state.download.model_id)
      ?.size,
);
const statusText: Record<string, string> = {
  preparing: "正在读取文件列表",
  downloading: "正在下载",
  pausing: "正在暂停",
  paused: "下载已暂停",
  completed: "下载完成",
  error: "下载遇到问题",
};

async function changeSource(source: Source) {
  await props.action(
    "/settings",
    { ...props.state.settings, source },
    "PUT",
    "下载源已更新",
  );
}
function download(model: Model) {
  void props.action("/download", { model_id: model.id });
}
function start(model: Model) {
  void props.action("/deploy/start", { model_id: model.id });
}
</script>

<template>
  <section class="models-page">
    <div class="hero">
      <div class="hero-copy">
        <div class="eyebrow"><span /> LOCAL MODELS. LIMITLESS WORDS.</div>
        <h1>让语言，不再是边界<span>。</span></h1>
        <p>
          把 Index-Translate 带到你的桌面。<br />从下载到翻译，让强大的多语言模型触手可及。
        </p>
        <div class="hero-tags">
          <span
            ><el-icon><CircleCheckFilled /></el-icon>150 种语言</span
          ><span>本地部署</span><span>开放 API</span>
        </div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="orbital orbital-one" />
        <div class="orbital orbital-two" />
        <span class="art-caption">A WORLD OF UNDERSTANDING</span>
        <div class="language-tile tile-cn">译<span>中文</span></div>
        <div class="language-tile tile-en">A<span>English</span></div>
        <div class="language-tile tile-ja">あ<span>日本語</span></div>
        <span class="art-spark spark-one">✦</span
        ><span class="art-spark spark-two">＋</span>
      </div>
    </div>
    <div class="overview-strip">
      <div>
        <span class="metric-icon"
          ><el-icon><FolderOpened /></el-icon
        ></span>
        <div>
          <span class="metric-label">本地模型</span
          ><strong
            >{{ readyCount }} <small>/ 3</small
            ><span class="metric-note">已就绪</span></strong
          >
        </div>
      </div>
      <div>
        <span class="metric-icon"
          ><el-icon><Cpu /></el-icon
        ></span>
        <div>
          <span class="metric-label">设备内存</span
          ><strong
            >{{
              state.hardware.memory_total
                ? bytes(state.hardware.memory_total)
                : "—"
            }}<span class="metric-note">{{
              state.hardware.platform || "桌面端自动检测"
            }}</span></strong
          >
        </div>
      </div>
      <div>
        <span class="metric-icon"
          ><el-icon><Connection /></el-icon
        ></span>
        <div>
          <span class="metric-label">本地 API</span
          ><strong class="mono"
            >:{{ state.settings.port
            }}<span class="metric-note"
              ><span
                class="status-dot"
                :class="{ online: state.deployment.status === 'running' }"
              />{{
                state.deployment.status === "running"
                  ? "服务运行中"
                  : "等待启动"
              }}</span
            ></strong
          >
        </div>
      </div>
    </div>
    <div class="section-heading">
      <div>
        <h2>选择你的翻译模型 <span class="count-badge">03</span></h2>
        <p>从轻量体验到高质量翻译，找到适合你设备的选择。</p>
      </div>
      <div class="source-select">
        <span>下载源</span
        ><el-select
          aria-label="模型下载源"
          :model-value="state.settings.source"
          :disabled="activeDownload || deployed"
          @change="changeSource"
          ><el-option
            v-for="source in sources"
            :key="source.value"
            :value="source.value"
            :label="source.label"
            ><span>{{ source.label }}</span
            ><span class="option-hint">{{ source.hint }}</span></el-option
          ></el-select
        >
      </div>
    </div>
    <div class="model-grid">
      <article
        v-for="model in state.models"
        :key="model.id"
        :class="[
          'model-card',
          {
            featured: model.id === '2b',
            'model-running': state.deployment.model_id === model.id && deployed,
          },
        ]"
      >
        <div class="model-card-top">
          <span :class="['model-mark', `mark-${model.id}`]"
            ><el-icon :size="22"><Cpu /></el-icon></span
          ><span :class="['model-badge', { preview: model.preview }]">{{
            model.badge
          }}</span>
        </div>
        <p class="model-family">{{ model.name }}</p>
        <h3>{{ model.size }}<small v-if="model.preview">MoE</small></h3>
        <p class="model-description">{{ model.description }}</p>
        <div class="model-specs">
          <div>
            <span>模型权重</span
            ><strong>{{
              model.local.total
                ? bytes(model.local.total)
                : model.weight_gb
                  ? `约 ${model.weight_gb} GB`
                  : "下载前检查"
            }}</strong>
          </div>
          <div><span>覆盖语言</span><strong>150 种</strong></div>
          <div>
            <span>架构</span
            ><strong>{{ model.preview ? "Qwen3.5 MoE" : "Qwen3.5" }}</strong>
          </div>
        </div>
        <div class="memory-hint">
          <el-icon><Cpu /></el-icon><span>{{ model.memory }}</span>
        </div>
        <div v-if="model.local.status === 'ready'" class="model-local-state">
          <el-icon><CircleCheckFilled /></el-icon>已下载 · 校验完成
        </div>
        <div v-else class="model-local-state muted">
          <span class="status-dot" />{{
            model.local.status === "partial"
              ? `已缓存 ${bytes(model.local.downloaded)}`
              : model.preview
                ? "预览版 · 检查权重完整性"
                : "尚未下载到本地"
          }}
        </div>
        <el-button
          v-if="state.deployment.model_id === model.id && deployed"
          class="full-width"
          :loading="state.deployment.status !== 'running'"
          :icon="VideoPause"
          @click="action('/deploy/stop')"
          >{{
            state.deployment.status === "loading"
              ? "正在加载模型"
              : state.deployment.status === "stopping"
                ? "正在停止"
                : "停止服务"
          }}</el-button
        >
        <el-button
          v-else-if="model.local.status === 'ready'"
          type="primary"
          class="full-width"
          :icon="VideoPlay"
          :disabled="deployed || state.runtime.status !== 'ready'"
          :loading="pending === '/deploy/start'"
          @click="start(model)"
          >启动模型</el-button
        >
        <el-button
          v-else
          :type="model.id === '2b' ? 'primary' : 'default'"
          class="full-width"
          :icon="Download"
          :disabled="activeDownload"
          @click="download(model)"
          >{{
            activeDownload && state.download.model_id === model.id
              ? "下载进行中"
              : model.local.status === "partial"
                ? "继续下载"
                : model.preview
                  ? "检查并下载"
                  : "下载模型"
          }}</el-button
        >
      </article>
    </div>
    <div v-if="state.download.status !== 'idle'" class="download-panel surface">
      <div class="download-header">
        <div class="download-title">
          <span class="metric-icon"
            ><el-icon><Download /></el-icon
          ></span>
          <div>
            <strong>Index-Translate {{ activeName }}</strong>
            <p>
              {{ statusText[state.download.status]
              }}<span class="dot-separator">·</span
              ><span class="mono">{{ state.download.file }}</span>
            </p>
          </div>
        </div>
        <div class="inline-actions">
          <button class="text-button" @click="emit('logs')">查看日志</button
          ><el-button
            v-if="activeDownload"
            size="small"
            :disabled="state.download.status === 'pausing'"
            :icon="VideoPause"
            @click="action('/download/pause')"
            >暂停</el-button
          ><el-button
            v-else-if="state.download.status !== 'completed'"
            size="small"
            :icon="VideoPlay"
            @click="action('/download', { model_id: state.download.model_id })"
            >重试 / 继续</el-button
          >
        </div>
      </div>
      <el-progress
        :percentage="Number(percent.toFixed(1))"
        :stroke-width="5"
        :status="
          state.download.status === 'error'
            ? 'exception'
            : state.download.status === 'completed'
              ? 'success'
              : undefined
        "
      />
      <div class="download-meta">
        <span
          >{{ bytes(state.download.downloaded) }} /
          {{ bytes(state.download.total) }}</span
        ><span>{{
          state.download.speed
            ? `${bytes(state.download.speed)}/s`
            : "断点保留 · 自动校验"
        }}</span>
      </div>
      <p v-if="state.download.error" class="error-text">
        {{ state.download.error }}
      </p>
    </div>
    <div class="runtime-banner">
      <div class="runtime-icon">
        <el-icon :size="23"><Cpu /></el-icon>
      </div>
      <div>
        <strong>{{
          state.runtime.status === "ready"
            ? "推理环境已就绪"
            : state.runtime.status === "installing"
              ? "正在准备推理环境"
              : "再准备一个环境，就能开始翻译"
        }}</strong>
        <p>
          {{
            state.runtime.status === "ready"
              ? "下载模型后点击启动，即可在翻译体验页使用，也可以连接第三方应用。"
              : "Python 已随桌面应用内嵌。首次使用安装 PyTorch 与 Transformers，之后即可离线推理。"
          }}
        </p>
        <p v-if="state.runtime.error" class="error-text">
          {{ state.runtime.error }}
        </p>
      </div>
      <el-button
        v-if="state.runtime.status !== 'ready'"
        :loading="state.runtime.status === 'installing'"
        :icon="state.runtime.status === 'installing' ? Loading : Download"
        @click="action('/runtime/install')"
        >{{
          state.runtime.status === "installing" ? "安装中" : "安装推理依赖"
        }}</el-button
      ><el-button v-else text @click="emit('navigate', 'translate')"
        >去翻译<el-icon class="el-icon--right"><ArrowRight /></el-icon
      ></el-button>
    </div>
    <p v-if="state.deployment.error" class="notice error-notice">
      {{ state.deployment.error }}
    </p>
    <div class="library-footnote">
      <span
        >提示：内存需求与精度、上下文长度有关。CPU / MPS 使用 FP32，首次体验推荐
        2B。</span
      ><button class="text-button" @click="emit('navigate', 'settings')">
        管理存储与部署设置 <span>↗</span>
      </button>
    </div>
  </section>
</template>
