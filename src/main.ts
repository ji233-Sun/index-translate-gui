import { createApp } from "vue";
import {
  ElButton,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElProgress,
  ElSelect,
  ElSwitch,
} from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import "./style.css";

const app = createApp(App);
const components = {
  ElButton,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElProgress,
  ElSelect,
  ElSwitch,
};
for (const [name, component] of Object.entries(components))
  app.component(name, component);
app.mount("#app");
