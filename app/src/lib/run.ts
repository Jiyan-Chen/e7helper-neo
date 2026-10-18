import { isDev } from "./env";

/**
 * 启动任务 / 建计划时实际发给引擎的配置。
 * 正式版没有演练开关，一律 dry_run=false（用户意见）；开发版用保存的设置（默认演练）。
 * 引擎这边模块的 dry_run 默认仍是 true，CLI 不受影响。
 */
export function runConfig(config: Record<string, unknown>): Record<string, unknown> {
  if (!("dry_run" in config)) return config;
  return isDev ? config : { ...config, dry_run: false };
}

/** 这份配置跑起来是不是演练（只有开发版可能是）。 */
export function isDryRun(config: Record<string, unknown> | null | undefined): boolean {
  return !!config && config.dry_run === true;
}
