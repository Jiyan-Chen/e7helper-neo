// 开发版 / 正式版的区别（用户意见：正式版面向玩家，开发者功能只在开发版出现）：
// - 演练（dry_run）开关只在开发版显示，默认演练；正式版启动任务和建计划一律 dry_run=false；
// - 模板采集、示例模块、原始日志（带来源）、内部场景名只在开发版出现。
// `pnpm tauri dev` / `pnpm dev` 是开发版；打包后是正式版。VITE_E7_DEV=1 可以在打包版里打开开发者功能。
export const isDev: boolean = import.meta.env.DEV || import.meta.env.VITE_E7_DEV === "1";
