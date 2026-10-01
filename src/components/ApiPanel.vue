<script setup lang="ts">
import { computed, ref } from "vue";
import {
  CopyDocument,
  Connection,
  Key,
  Right,
  CircleCheckFilled,
} from "@element-plus/icons-vue";
import { copy } from "../useStudio";
import type { Snapshot } from "../types";

const props = defineProps<{ state: Snapshot }>();
const emit = defineEmits<{ settings: [] }>();
const protocol = ref("chat");
const protocols = [
  {
    id: "chat",
    name: "Chat Completions",
    path: "/v1/chat/completions",
    brand: "OpenAI",
  },
  {
    id: "responses",
    name: "Responses",
    path: "/v1/responses",
    brand: "OpenAI",
  },
  {
    id: "messages",
    name: "Messages",
    path: "/v1/messages",
    brand: "Anthropic",
  },
  {
    id: "completions",
    name: "Completions",
    path: "/v1/completions",
    brand: "OpenAI · Legacy",
  },
];
const current = computed(
  () => protocols.find((item) => item.id === protocol.value)!,
);
const base = computed(() => `http://127.0.0.1:${props.state.settings.port}`);
const model = computed(
  () =>
    props.state.models.find(
      (model) => model.id === props.state.deployment.model_id,
    )?.repo || "IndexTeam/Index-Translate-2B",
);
const example = computed(() => {
  const prompt =
    "请将以下文本翻译为英语，直接输出翻译结果，不要进行任何解释。\n\n你好，世界。";
  const data = {
    model: model.value,
    stream: true,
    ...(protocol.value === "responses"
      ? { input: prompt, max_output_tokens: 1024, store: false }
      : protocol.value === "completions"
        ? { prompt, max_tokens: 1024 }
        : { messages: [{ role: "user", content: prompt }], max_tokens: 1024 }),
  };
  const auth =
    protocol.value === "messages"
      ? '-H "x-api-key: $INDEX_API_KEY" \\\n  -H "anthropic-version: 2023-06-01"'
      : '-H "Authorization: Bearer $INDEX_API_KEY"';
  return `curl -N ${base.value}${current.value.path} \\\n  ${auth} \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(data, null, 2)}'`;
});
</script>

<template>
  <section class="api-page">
    <div class="page-heading">
      <div class="eyebrow">BUILT TO CONNECT</div>
      <h1>你的模型，连接你的工作流。</h1>
      <p>熟悉的 API 格式，把本地翻译能力接入你习惯的工具。</p>
    </div>
    <div class="api-connection surface">
      <div class="api-connection-heading">
        <span class="metric-icon"
          ><el-icon><Connection /></el-icon
        ></span>
        <div>
          <h2>本地 API 服务</h2>
          <p>
            {{
              state.settings.host === "0.0.0.0"
                ? "已允许局域网访问，请使用本机局域网 IP 连接。"
                : "仅监听本机，使用访问密钥连接。"
            }}
          </p>
        </div>
        <span
          :class="[
            'service-badge',
            { online: state.deployment.status === 'running' },
          ]"
          ><span
            class="status-dot"
            :class="{ online: state.deployment.status === 'running' }"
          />{{
            state.deployment.status === "running"
              ? "服务运行中"
              : "等待模型启动"
          }}</span
        >
      </div>
      <div class="connection-fields">
        <div>
          <label>OPENAI BASE URL</label>
          <div class="copy-field">
            <code>{{ base }}/v1</code
            ><button
              class="icon-button"
              aria-label="复制 OpenAI Base URL"
              @click="copy(base + '/v1')"
            >
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
        </div>
        <div>
          <label>ANTHROPIC BASE URL</label>
          <div class="copy-field">
            <code>{{ base }}</code
            ><button
              class="icon-button"
              aria-label="复制 Anthropic Base URL"
              @click="copy(base)"
            >
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
        </div>
      </div>
      <div class="api-key-line">
        <el-icon><Key /></el-icon><span>访问密钥</span
        ><code>{{
          state.settings.api_key
            ? "it-••••••••••••••••••••"
            : "在桌面端自动生成"
        }}</code
        ><button
          class="text-button"
          :disabled="!state.settings.api_key"
          @click="copy(state.settings.api_key, '访问密钥已复制')"
        >
          复制密钥</button
        ><button class="text-button" @click="emit('settings')">
          修改设置 <el-icon><Right /></el-icon>
        </button>
      </div>
    </div>
    <div class="section-heading">
      <div>
        <h2>几行代码，即刻连接</h2>
        <p>将密钥设置为 INDEX_API_KEY 环境变量。以下为 Bash / zsh 示例。</p>
      </div>
      <span class="subtle-tag"
        ><el-icon><CircleCheckFilled /></el-icon> 支持 SSE 流式响应</span
      >
    </div>
    <div class="code-surface">
      <div class="protocol-tabs" role="tablist" aria-label="接口协议">
        <button
          v-for="item in protocols"
          :key="item.id"
          :class="{ active: protocol === item.id }"
          role="tab"
          :aria-selected="protocol === item.id"
          @click="protocol = item.id"
        >
          <span>{{ item.brand }}</span
          >{{ item.name }}
        </button>
      </div>
      <div class="code-heading">
        <span><span class="http-method">POST</span> {{ current.path }}</span
        ><button @click="copy(example, '调用示例已复制')">
          <el-icon><CopyDocument /></el-icon>复制代码
        </button>
      </div>
      <pre><code>{{ example }}</code></pre>
    </div>
    <div class="api-notes">
      <div>
        <strong>适用于翻译工作流</strong>
        <p>
          支持文本消息、系统提示、流式响应、停止字符串和真实 token 用量。<code
            >GET /v1/models</code
          >
          可查询当前模型。
        </p>
      </div>
      <div>
        <strong>明确的兼容边界</strong>
        <p>
          不支持工具调用、多模态、结构化 JSON 输出或 Responses
          历史存储。模型一次处理一条请求，忙碌时返回 429。
        </p>
      </div>
    </div>
  </section>
</template>
