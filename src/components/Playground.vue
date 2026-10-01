<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  CopyDocument,
  Right,
  Switch,
  VideoPause,
  MagicStick,
  Document,
  Close,
} from "@element-plus/icons-vue";
import { copy } from "../useStudio";
import type { Action, Snapshot } from "../types";

const props = defineProps<{ state: Snapshot; action: Action }>();
const emit = defineEmits<{ models: [] }>();
const text = ref("");
const source = ref("auto");
const target = ref("en");
const instruction = ref("");
const languages = [
  ["zh", "简体中文"],
  ["en", "英语"],
  ["ja", "日语"],
  ["ko", "韩语"],
  ["fr", "法语"],
  ["de", "德语"],
  ["es", "西班牙语"],
  ["ru", "俄语"],
  ["pt", "葡萄牙语"],
  ["ar", "阿拉伯语"],
  ["it", "意大利语"],
  ["vi", "越南语"],
  ["th", "泰语"],
  ["id", "印尼语"],
];
const running = computed(() => props.state.deployment.status === "running");
const translating = computed(
  () => props.state.translation.status === "running",
);
const model = computed(() =>
  props.state.models.find(
    (model) => model.id === props.state.deployment.model_id,
  ),
);
const examples = [
  {
    name: "日常表达",
    text: "最好的旅行，不是到达某个地方，而是用新的眼光看待世界。",
    target: "en",
    instruction: "",
  },
  {
    name: "保留格式",
    text: '{"title": "⭐版本更新公告⭐", "content": "欢迎来到新的世界！#版本更新#"}',
    target: "ja",
    instruction: "保留 JSON 结构、星号和中文话题标签。",
  },
  {
    name: "自然语气",
    text: "感谢你一直以来的耐心与支持。我们正在让每一次体验变得更好。",
    target: "en",
    instruction: "语气友好、自然，适合产品更新邮件。",
  },
];
function swap() {
  if (source.value === "auto") return;
  [source.value, target.value] = [target.value, source.value];
  if (props.state.translation.text) text.value = props.state.translation.text;
}
async function translate() {
  if (text.value.trim() && !translating.value) {
    await props.action("/translate", {
      text: text.value,
      source: source.value,
      target: target.value,
      instruction: instruction.value,
    });
  }
}
function keyboard(event: KeyboardEvent) {
  if (
    !(event.target instanceof HTMLElement) ||
    !event.target.closest(".playground-page")
  )
    return;
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    void translate();
  }
  if (event.key === "Escape" && translating.value)
    void props.action("/translate/cancel");
}
onMounted(() => window.addEventListener("keydown", keyboard));
onUnmounted(() => window.removeEventListener("keydown", keyboard));
</script>

<template>
  <section class="playground-page">
    <div class="page-heading">
      <div class="eyebrow">TRANSLATION PLAYGROUND</div>
      <h1>每一句话，都值得被理解。</h1>
      <p>一段文字，一种新的表达。体验专注翻译的本地模型。</p>
    </div>
    <div v-if="!running" class="notice">
      <el-icon><Document /></el-icon
      ><span>先启动一个模型，开始你的第一段翻译。</span
      ><el-button size="small" @click="emit('models')"
        >前往模型工作台 <el-icon><Right /></el-icon
      ></el-button>
    </div>
    <div class="translator surface">
      <div class="language-toolbar">
        <div>
          <el-select
            v-model="source"
            aria-label="源语言"
            filterable
            allow-create
            default-first-option
            ><el-option value="auto" label="自动识别语言" /><el-option
              v-for="[value, label] in languages"
              :key="value"
              :value="value!"
              :label="label"
          /></el-select>
        </div>
        <button
          class="icon-button swap-button"
          aria-label="交换语言"
          :disabled="source === 'auto'"
          @click="swap"
        >
          <el-icon :size="19"><Switch /></el-icon>
        </button>
        <div>
          <el-select
            v-model="target"
            aria-label="目标语言"
            filterable
            allow-create
            default-first-option
            ><el-option
              v-for="[value, label] in languages"
              :key="value"
              :value="value!"
              :label="label" /></el-select
          ><span class="subtle-tag">译文</span>
        </div>
      </div>
      <div class="translation-columns">
        <div class="translation-input">
          <textarea
            v-model="text"
            aria-label="待翻译的文本"
            maxlength="50000"
            placeholder="在这里输入或粘贴你想翻译的内容…"
            :disabled="translating"
          />
          <div class="translation-bottom">
            <span>{{ text.length.toLocaleString() }} / 50,000</span
            ><button
              class="icon-button"
              aria-label="清空原文"
              :disabled="!text || translating"
              @click="text = ''"
            >
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </div>
        <div
          class="translation-output"
          aria-label="翻译结果"
          aria-live="polite"
        >
          <div v-if="state.translation.text" class="translated-text">
            {{ state.translation.text
            }}<span v-if="translating" class="typing-cursor" />
          </div>
          <div v-else class="translation-empty">
            <div class="empty-glyph">A<span>译</span></div>
            <strong>{{
              translating ? "正在理解你的文字…" : "让文字，遇见另一种语言"
            }}</strong>
            <p>
              {{
                translating
                  ? "模型正在生成，译文将在这里实时显示。"
                  : "译文会出现在这里。"
              }}
            </p>
          </div>
          <div class="translation-bottom">
            <span>{{
              state.translation.output_tokens
                ? `${state.translation.output_tokens} tokens · ${state.translation.elapsed.toFixed(1)} 秒`
                : "本地推理 · 文本不上传"
            }}</span
            ><button
              class="icon-button"
              aria-label="复制译文"
              :disabled="!state.translation.text"
              @click="copy(state.translation.text, '译文已复制')"
            >
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
        </div>
      </div>
      <div class="translation-actions">
        <div class="inline-actions">
          <span class="status-dot" :class="{ online: running }" /><span>{{
            running
              ? `${model?.size} · ${state.hardware.device.toUpperCase()}`
              : "等待模型启动"
          }}</span>
        </div>
        <div class="inline-actions">
          <span class="shortcut-hint">⌘ / Ctrl + Enter</span
          ><el-button
            v-if="translating"
            :icon="VideoPause"
            @click="action('/translate/cancel')"
            >停止生成</el-button
          ><el-button
            v-else
            type="primary"
            :icon="MagicStick"
            :disabled="!text.trim() || !running"
            @click="translate"
            >开始翻译</el-button
          >
        </div>
      </div>
    </div>
    <p v-if="state.translation.error" class="notice error-notice">
      {{ state.translation.error }}
    </p>
    <div class="instruction-box">
      <label for="instruction">让译文更合你意 <span>可选</span></label
      ><el-input
        id="instruction"
        v-model="instruction"
        placeholder="例如：保留 Markdown 格式、将 Studio 统一译为工作室、使用自然友好的语气…"
        maxlength="2000"
        :disabled="translating"
      /><span class="small-help"
        >目标语言支持搜索或直接输入语言名称，不限于下拉列表。</span
      >
    </div>
    <div class="examples">
      <span>试着翻译</span
      ><button
        v-for="example in examples"
        :key="example.name"
        :disabled="translating"
        @click="
          text = example.text;
          target = example.target;
          instruction = example.instruction;
        "
      >
        {{ example.name }} <span>↗</span>
      </button>
    </div>
  </section>
</template>
