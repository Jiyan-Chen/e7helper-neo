// 内部名称 → 玩家看得懂的叫法。
import type { LogRecord, TaskStatus, Trigger } from "./types";

const SCENES: Record<string, string> = {
  lobby: "大厅",
  secret_shop: "秘密商店",
  shop: "商店",
  arena: "竞技场",
  sanctuary: "圣域",
  arena_main: "竞技场",
  arena_npc: "NPC对战",
  arena_prep: "准备战斗",
  arena_battle: "战斗中",
  arena_result: "战斗结算",
  daily_mail: "邮件",
  daily_forest: "精灵之森",
  daily_covenant: "誓约召唤",
  daily_summon: "召唤",
  daily_summon_anim: "召唤中",
  daily_summon_hero: "召唤结果",
  daily_summon_results: "召唤结果",
  rb_menu: "战斗",
  rb_hunt: "讨伐",
  rb_prep: "准备战斗",
  rb_battle: "战斗中",
  rb_clear: "战斗胜利",
  rb_result: "战斗结算",
  rb_after: "战斗结算",
};

const POPUPS: Record<string, string> = {
  disconnected: "连接中断",
  announcement: "游戏公告",
  title_start: "标题画面",
  network: "网络异常",
  notice: "通知",
  confirm: "确认框",
  obscured: "弹窗",
};

/** 场景名（模块场景带 <module>: 前缀时去掉）。认不出时返回「游戏中」。 */
export function sceneLabel(scene: string | null | undefined, popup?: string | null): string {
  if (popup) return POPUPS[popup] ?? "弹窗";
  if (!scene) return "游戏中";
  const key = scene.includes(":") ? scene.split(":").pop()! : scene;
  return SCENES[key] ?? "游戏中";
}

export const STATUS_LABEL: Record<TaskStatus, string> = {
  running: "进行中",
  succeeded: "完成",
  failed: "失败",
  stopped: "已停止",
  timeout: "超时",
  stuck: "卡住了",
};

export function statusLabel(s: string | null | undefined): string {
  return s ? (STATUS_LABEL[s as TaskStatus] ?? s) : "—";
}

/** 任务从哪来：手动 / 计划。 */
export function sourceLabel(source: string): string {
  return source.startsWith("schedule") ? "计划" : "手动";
}

export function triggerLabel(t: Trigger): string {
  switch (t.type) {
    case "interval":
      return t.minutes % 60 === 0 ? `每 ${t.minutes / 60} 小时` : `每 ${t.minutes} 分钟`;
    case "daily":
      return `每天 ${t.at}`;
    case "module":
      return "按游戏时间";
  }
}

let moduleNames: Record<string, string> = {};

/** 模块 id → 菜单上的名字（模块列表加载后由 App 设置）。 */
export function setModuleNames(names: Record<string, string>) {
  moduleNames = names;
}

export function moduleName(id: string): string {
  return moduleNames[id] ?? id;
}

/** 日志正文换成玩家看得懂的话：英文状态换中文、计划 id 换成功能名。 */
export function friendlyMessage(msg: string): string {
  return msg
    .replace(/任务结束：(succeeded|failed|stopped|timeout|stuck)/, (_, s: TaskStatus) => `任务结束：${STATUS_LABEL[s]}`)
    .replace(/计划 [0-9a-f]+（(\w+)）/g, (_, m: string) => `计划「${moduleName(m)}」`)
    .replace(/\.next_due 出错/, "计算下次时间出错")
    .replace(/dry-run/g, "演练");
}

/** 「动态」里日志前面显示的功能名（模块日志才有）。 */
export function activitySource(r: LogRecord): string | null {
  return r.name.startsWith("module.") ? moduleName(r.name.slice(7)) : null;
}

/** 玩家视角的「动态」只看：模块自己的日志、设备连接、计划，以及任何警告和错误。 */
export function isActivity(r: LogRecord): boolean {
  if (r.name.startsWith("uvicorn")) return false;
  if (r.level === "WARNING" || r.level === "ERROR" || r.level === "CRITICAL") return true;
  if (r.name === "e7helper.api.engine") return !r.message.startsWith("经 API");
  return r.name.startsWith("module.") || r.name === "e7helper.api.scheduler";
}

/** 任务的错误（可能是整段 traceback）→ 最后一行，去掉异常类名。 */
export function friendlyError(error: string | null | undefined): string | null {
  if (!error) return null;
  const lines = error.trim().split(/\r?\n/).filter((l) => l.trim());
  const last = lines[lines.length - 1] ?? "";
  return last.replace(/^[\w.]+(Error|Exception|Anomaly|Failed|Timeout|Stuck|Stopped|Busy)\s*:\s*/, "") || last;
}
