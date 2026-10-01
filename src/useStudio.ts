import { onMounted, onUnmounted, ref } from "vue";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { ElMessage } from "element-plus";
import { initialSnapshot, type Action, type Snapshot } from "./types";

export function useStudio() {
  const state = ref(initialSnapshot());
  const desktop = isTauri();
  const connecting = ref(false);
  const connected = ref(false);
  const error = ref("");
  const bootstrapLogs = ref<string[]>([]);
  const pending = ref("");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unlisten: UnlistenFn | undefined;
  let disposed = false;

  async function refresh() {
    state.value = await invoke<Snapshot>("backend_request", {
      method: "GET",
      path: "/status",
      body: null,
    });
  }
  async function poll() {
    if (disposed || !connected.value) return;
    try {
      await refresh();
      error.value = "";
    } catch (cause) {
      connected.value = false;
      error.value = String(cause);
    }
    if (!disposed)
      timer = setTimeout(
        poll,
        state.value.translation.status === "running" ? 300 : 1200,
      );
  }
  async function connect() {
    if (!desktop || connecting.value) return;
    connecting.value = true;
    error.value = "";
    clearTimeout(timer);
    try {
      state.value = await invoke<Snapshot>("backend_start");
      connected.value = true;
      timer = setTimeout(poll, 500);
    } catch (cause) {
      error.value = String(cause);
      connected.value = false;
    } finally {
      connecting.value = false;
    }
  }
  const action: Action = async (
    path,
    body = null,
    method = "POST",
    message = "",
  ) => {
    if (!desktop) {
      ElMessage.info(
        "这是浏览器界面预览，请在桌面应用中使用下载、部署和翻译功能。",
      );
      return false;
    }
    if (!connected.value) {
      ElMessage.warning("本地服务尚未连接，请先重试连接。");
      return false;
    }
    pending.value = path;
    try {
      await invoke("backend_request", { method, path, body });
      await refresh();
      if (message) ElMessage.success(message);
      return true;
    } catch (cause) {
      ElMessage.error(String(cause));
      return false;
    } finally {
      pending.value = "";
    }
  };
  onMounted(async () => {
    if (desktop) {
      unlisten = await listen<string>("bootstrap-log", (event) => {
        bootstrapLogs.value = [
          ...bootstrapLogs.value.slice(-40),
          event.payload,
        ];
      });
      await connect();
    }
  });
  onUnmounted(() => {
    disposed = true;
    clearTimeout(timer);
    unlisten?.();
  });
  return {
    state,
    desktop,
    connecting,
    connected,
    error,
    bootstrapLogs,
    pending,
    connect,
    action,
  };
}

export async function copy(value: string, label = "已复制") {
  try {
    await navigator.clipboard.writeText(value);
    ElMessage.success(label);
  } catch {
    ElMessage.error("剪贴板不可用，请手动选择并复制。");
  }
}
