import { Workflow } from "lucide-react";
import type { ModuleUI } from "../types";

// 自定义流程（B11）：不在菜单里单独出现，入口是「我的流程」页（/flows）。
const ui: ModuleUI = {
  id: "custom_flow",
  icon: Workflow,
  order: 90,
  menuLabel: "自定义流程",
  menuHidden: true,
  fieldIcons: { flow: Workflow },
};

export default ui;
