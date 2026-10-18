import { FlaskConical } from "lucide-react";
import type { ModuleUI } from "../types";

// 示例模块：只截图打印分辨率，只在开发版出现
const ui: ModuleUI = { id: "hello", icon: FlaskConical, order: 90, devOnly: true };

export default ui;
