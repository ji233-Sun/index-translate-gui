<script setup lang="ts">
import { computed, ref } from "vue";
import { ElConfigProvider } from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import {
  Box,
  Connection,
  Document,
  Setting,
  ArrowRight,
  Monitor,
  Check,
  Loading,
} from "@element-plus/icons-vue";
import { useStudio } from "./useStudio";
import type { Page } from "./types";
import ModelLibrary from "./components/ModelLibrary.vue";
import Playground from "./components/Playground.vue";
import ApiPanel from "./components/ApiPanel.vue";
import SettingsPanel from "./components/SettingsPanel.vue";

const {
  state,
  desktop,
  connecting,
  connected,
  error,
  bootstrapLogs,
  pending,
  connect,
  action,
} = useStudio();
const page = ref<Page>("models");
const logsOpen = ref(false);
const navigation = [
  { id: "models" as const, label: "模型工作台", icon: Box, caption: "模型" },
  {
    id: "translate" as const,
    label: "翻译体验",
    icon: Document,
    caption: "翻译",
  },
  { id: "api" as const, label: "API 接入", icon: Connection, caption: "接入" },
  {
    id: "settings" as const,
    label: "偏好设置",
    icon: Setting,
    caption: "设置",
  },
];
const running = computed(() => state.value.deployment.status === "running");
const currentModel = computed(() =>
  state.value.models.find(
    (model) => model.id === state.value.deployment.model_id,
  ),
);
const title = computed(
  () => navigation.find((item) => item.id === page.value)?.label,
);
</script>

<template>
  <ElConfigProvider :locale="zhCn">
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-symbol">译<span>↗</span></div>
          <div><strong>Index Translate</strong><span>STUDIO</span></div>
        </div>
        <div class="workspace-label">你的本地翻译空间</div>
        <nav aria-label="主导航">
          <button
            v-for="item in navigation"
            :key="item.id"
            :class="['nav-item', { active: page === item.id }]"
            :aria-current="page === item.id ? 'page' : undefined"
            @click="page = item.id"
          >
            <el-icon :size="19"><component :is="item.icon" /></el-icon
            ><span>{{ item.label }}</span
            ><span v-if="page === item.id" class="nav-dot" />
          </button>
        </nav>
        <div class="sidebar-bottom">
          <div class="local-card">
            <div class="local-card-icon">
              <el-icon><Monitor /></el-icon>
            </div>
            <strong>在本地，自由表达</strong>
            <p>模型留在你的设备上，<br />翻译内容由你掌握。</p>
            <span class="privacy-label"
              ><el-icon><Check /></el-icon> 本地推理 · 隐私优先</span
            >
          </div>
          <button class="logs-button" @click="logsOpen = true">
            <span class="status-dot" :class="{ online: connected }" />{{
              connected
                ? "本地服务已连接"
                : desktop
                  ? "本地服务未连接"
                  : "浏览器界面预览"
            }}<el-icon><ArrowRight /></el-icon>
          </button>
          <div class="sidebar-version">
            INDEX TRANSLATE STUDIO <span>v0.1.0</span>
          </div>
        </div>
      </aside>
      <section class="main-shell">
        <header class="topbar">
          <div class="breadcrumb">
            工作空间<el-icon><ArrowRight /></el-icon><span>{{ title }}</span>
          </div>
          <div class="topbar-right">
            <span class="local-pill"
              ><span class="status-dot" :class="{ online: running }" />{{
                running ? `${currentModel?.size} · 运行中` : "模型未启动"
              }}</span
            ><button
              class="icon-button"
              aria-label="打开偏好设置"
              @click="page = 'settings'"
            >
              <el-icon :size="18"><Setting /></el-icon>
            </button>
          </div>
        </header>
        <main>
          <div v-if="!desktop" class="notice preview-notice">
            <span>界面预览</span>下载、部署与翻译功能在 Tauri
            桌面应用中使用。<code>npm run desktop</code>
          </div>
          <div v-if="connecting" class="notice">
            <el-icon class="is-loading"><Loading /></el-icon>正在启动内嵌 Python
            服务…<span class="muted">{{ bootstrapLogs.at(-1) }}</span>
          </div>
          <div v-if="error" class="notice error-notice">
            <span>{{ error }}</span
            ><el-button size="small" @click="connect">重新连接</el-button
            ><el-button size="small" text @click="logsOpen = true"
              >启动日志</el-button
            >
          </div>
          <ModelLibrary
            v-show="page === 'models'"
            :state="state"
            :action="action"
            :pending="pending"
            :desktop="desktop"
            @navigate="page = $event"
            @logs="logsOpen = true"
          />
          <Playground
            v-show="page === 'translate'"
            :state="state"
            :action="action"
            @models="page = 'models'"
          />
          <ApiPanel
            v-show="page === 'api'"
            :state="state"
            @settings="page = 'settings'"
          />
          <SettingsPanel
            v-show="page === 'settings'"
            :state="state"
            :action="action"
            :desktop="desktop"
            :pending="pending"
            @logs="logsOpen = true"
          />
          <footer class="page-footer">
            <span>基于哔哩哔哩 Index-Translate 开源模型 · 社区桌面客户端</span
            ><span>让每一种表达，都被理解。 ↗</span>
          </footer>
        </main>
      </section>
      <el-drawer v-model="logsOpen" title="运行日志" size="560px">
        <p class="muted">
          包含环境安装、下载和部署状态；不记录翻译正文或 API 密钥。
        </p>
        <div class="log-list">
          <div
            v-for="(line, index) in bootstrapLogs"
            :key="`boot-${index}`"
            class="log-line"
          >
            <span>启动</span><code>{{ line }}</code>
          </div>
          <div
            v-for="(entry, index) in state.logs"
            :key="index"
            :class="['log-line', entry.level]"
          >
            <span>{{ new Date(entry.time * 1000).toLocaleTimeString() }}</span
            ><code>{{ entry.message }}</code>
          </div>
          <el-empty
            v-if="!state.logs.length && !bootstrapLogs.length"
            description="暂无运行日志"
          />
        </div>
      </el-drawer>
    </div>
  </ElConfigProvider>
</template>
