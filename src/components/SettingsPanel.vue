<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import {
  FolderOpened,
  Refresh,
  Check,
  Cpu,
  Setting,
  Download,
} from "@element-plus/icons-vue";
import { open } from "@tauri-apps/plugin-dialog";
import { ElMessage } from "element-plus";
import {
  bytes,
  sources,
  type Action,
  type Settings,
  type Snapshot,
} from "../types";

const props = defineProps<{
  state: Snapshot;
  action: Action;
  desktop: boolean;
  pending: string;
}>();
const emit = defineEmits<{ logs: [] }>();
const form = reactive<Settings>({ ...props.state.settings });
watch(
  () => JSON.stringify(props.state.settings),
  () => Object.assign(form, props.state.settings),
);
const locked = computed(
  () =>
    ["loading", "running", "stopping"].includes(
      props.state.deployment.status,
    ) ||
    ["preparing", "downloading", "pausing"].includes(
      props.state.download.status,
    ) ||
    props.state.runtime.status === "installing",
);
const dirty = computed(
  () => JSON.stringify(form) !== JSON.stringify(props.state.settings),
);
async function chooseDirectory() {
  if (!props.desktop) {
    ElMessage.info("请在桌面应用中选择本地目录。");
    return;
  }
  try {
    const result = await open({
      directory: true,
      multiple: false,
      title: "选择模型存储目录",
      defaultPath: form.model_dir || undefined,
    });
    if (result) form.model_dir = result;
  } catch (cause) {
    ElMessage.error(String(cause));
  }
}
function generateKey() {
  const values = crypto.getRandomValues(new Uint8Array(24));
  form.api_key =
    "it-" +
    Array.from(values, (value) => value.toString(16).padStart(2, "0")).join("");
}
async function save() {
  if (!Number.isInteger(form.port) || form.port < 1024 || form.port > 65535) {
    ElMessage.error("端口须为 1024–65535 之间的整数");
    return;
  }
  if (form.api_key.length < 16 || !/^[\x21-\x7E]+$/.test(form.api_key)) {
    ElMessage.error("访问密钥至少 16 位，且不能含空格或非 ASCII 字符");
    return;
  }
  if (form.max_tokens >= form.max_context) {
    ElMessage.error("输出上限必须小于上下文长度");
    return;
  }
  await props.action("/settings", { ...form }, "PUT", "设置已保存");
}
</script>

<template>
  <section class="settings-page">
    <div class="page-heading">
      <div class="eyebrow">MAKE IT YOURS</div>
      <h1>让工作空间，适合你的习惯。</h1>
      <p>管理存储、推理与连接。一切都在你的掌控中。</p>
    </div>
    <div v-if="locked" class="notice">
      请先停止模型、暂停下载并等待环境安装完成，再修改设置。
    </div>
    <el-form :model="form" label-position="top" :disabled="locked">
      <div class="settings-section surface">
        <div class="settings-section-heading">
          <el-icon><Setting /></el-icon>
          <div>
            <h2>服务与访问</h2>
            <p>为第三方应用提供一个稳定的本地入口。</p>
          </div>
        </div>
        <div class="form-grid">
          <el-form-item label="API 端口"
            ><el-input-number
              v-model="form.port"
              :min="1024"
              :max="65535"
              :step="1"
              :precision="0"
              controls-position="right"
            />
            <p class="field-help">
              默认 8765，保存后下次启动生效。
            </p></el-form-item
          ><el-form-item label="访问范围"
            ><div class="switch-field">
              <el-switch
                :model-value="form.host === '0.0.0.0'"
                @change="form.host = $event ? '0.0.0.0' : '127.0.0.1'"
              /><span>允许局域网访问</span>
            </div>
            <p class="field-help">
              {{
                form.host === "0.0.0.0"
                  ? "监听所有网卡，局域网客户端仍需密钥。请勿直接暴露到公网。"
                  : "仅本机应用可以连接。"
              }}
            </p></el-form-item
          >
        </div>
        <el-form-item label="API 访问密钥"
          ><div class="input-action">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              autocomplete="off"
              placeholder="至少 16 个字符"
            /><el-button :icon="Refresh" @click="generateKey"
              >重新生成</el-button
            >
          </div>
          <p class="field-help">
            密钥只保存在本机设置文件中。重新生成后，需同步更新第三方应用。
          </p></el-form-item
        >
      </div>
      <div class="settings-section surface">
        <div class="settings-section-heading">
          <el-icon><FolderOpened /></el-icon>
          <div>
            <h2>下载与存储</h2>
            <p>选择连接更顺畅的来源，让模型在合适的位置安家。</p>
          </div>
        </div>
        <el-form-item label="模型存储目录"
          ><div class="input-action">
            <el-input
              v-model="form.model_dir"
              placeholder="输入模型目录的绝对路径"
            /><el-button :icon="FolderOpened" @click="chooseDirectory"
              >浏览</el-button
            >
          </div>
          <p class="field-help">
            可用空间
            {{
              state.hardware.disk_free
                ? bytes(state.hardware.disk_free)
                : "将在桌面端检测"
            }}。更换目录不会移动已有文件。
          </p></el-form-item
        >
        <div class="form-grid">
          <el-form-item label="默认下载源"
            ><el-select v-model="form.source"
              ><el-option
                v-for="source in sources"
                :key="source.value"
                :value="source.value"
                :label="
                  source.label + ' · ' + source.hint
                " /></el-select></el-form-item
          ><el-form-item label="自定义 Hugging Face 镜像"
            ><el-input
              v-model="form.mirror_url"
              placeholder="https://hf-mirror.com"
              :disabled="form.source !== 'custom'"
            />
            <p class="field-help">
              选择自定义源后生效，需兼容 Hugging Face Hub API。
            </p></el-form-item
          >
        </div>
      </div>
      <div class="settings-section surface">
        <div class="settings-section-heading">
          <el-icon><Cpu /></el-icon>
          <div>
            <h2>本地推理</h2>
            <p>从轻量模型和短上下文开始，按设备能力调整。</p>
          </div>
        </div>
        <div class="form-grid three">
          <el-form-item label="计算设备"
            ><el-select v-model="form.device"
              ><el-option
                value="auto"
                label="自动 · CUDA → MPS → CPU" /><el-option
                value="cuda"
                label="NVIDIA CUDA" /><el-option
                value="mps"
                label="Apple MPS" /><el-option
                value="cpu"
                label="CPU" /></el-select></el-form-item
          ><el-form-item label="上下文长度 (tokens)"
            ><el-input-number
              v-model="form.max_context"
              :min="512"
              :max="32768"
              :step="512"
              :precision="0"
              controls-position="right" /></el-form-item
          ><el-form-item label="最大输出 (tokens)"
            ><el-input-number
              v-model="form.max_tokens"
              :min="1"
              :max="8192"
              :step="128"
              :precision="0"
              controls-position="right"
          /></el-form-item>
        </div>
        <p class="field-help">
          上下文包含输入与输出。更长的上下文会消耗更多内存；CPU / MPS 使用
          FP32，CUDA 按硬件选择 BF16 / FP16。
        </p>
      </div>
      <div class="settings-save">
        <span>{{ dirty ? "有未保存的修改" : "设置已同步" }}</span
        ><el-button
          :disabled="!dirty"
          @click="Object.assign(form, state.settings)"
          >还原修改</el-button
        ><el-button
          type="primary"
          :icon="Check"
          :disabled="!dirty"
          :loading="pending === '/settings'"
          @click="save"
          >保存设置</el-button
        >
      </div>
    </el-form>
    <div class="runtime-banner">
      <div class="runtime-icon">
        <el-icon><Cpu /></el-icon>
      </div>
      <div>
        <strong>独立的运行环境</strong>
        <p>安装包内嵌 Python 3.12；推理依赖使用 uv 安装到应用目录。</p>
      </div>
      <el-button
        v-if="state.runtime.status !== 'ready'"
        :icon="Download"
        :loading="state.runtime.status === 'installing'"
        @click="action('/runtime/install')"
        >安装推理依赖</el-button
      ><button class="text-button" @click="emit('logs')">查看日志 ↗</button>
    </div>
  </section>
</template>
