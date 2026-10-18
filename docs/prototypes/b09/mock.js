// B09 原型共用的模拟数据（形状照抄 B08 接口：/api/status、/api/modules/daily/timers、/api/tasks/history、WS log 事件）
(function () {
  const now = Date.now();
  // 下一次每日重置：北京时间 3 点 = UTC 19:00
  const reset = new Date(now);
  reset.setUTCHours(19, 0, 0, 0);
  if (reset.getTime() <= now) reset.setUTCDate(reset.getUTCDate() + 1);
  const forest = new Date(now + (4 * 3600 + 20 * 60 + 15) * 1000);

  const status = {
    device: { connected: true, name: "MuMu#0 MuMu安卓设备", resolution: [1600, 900], backend: "ipc", index: 0 },
    task: null,
    scene: "lobby",
    scheduler: { paused: false, schedules: 2, next: forest.toISOString() },
  };

  const modules = [
    { id: "daily", name: "日常收取", kind: "task", group: "日常" },
    { id: "secret_shop", name: "刷神秘商店", kind: "task", group: "消耗" },
    { id: "arena_npc", name: "竞技场 NPC", kind: "task", group: "消耗" },
    { id: "repeat_battle", name: "重复刷关", kind: "task", group: "消耗" },
    { id: "hello", name: "示例模块", kind: "task", group: "开发" },
  ];

  const timers = [
    { key: "reset", label: "每日重置", at: reset.toISOString(), note: "北京时间 3:00" },
    { key: "forest", label: "精灵之森", at: forest.toISOString(), note: "精灵之泉 产出" },
    { key: "covenant", label: "誓约免费召唤", at: null, note: "今天已用完" },
  ];

  const fields = [
    { key: "mail", label: "邮件", desc: "领取剩余时间不到一天的邮件（逐封领取，不点「全部领取」）", value: true },
    { key: "forest", label: "精灵之森", desc: "领取企鹅巢穴 / 精灵之泉 / 魔罗戈拉的产出，有「照料」就照料", value: true },
    { key: "covenant", label: "誓约召唤", desc: "用完当天的免费召唤（优先免费十连；只点显示「免费」的按钮）", value: true },
  ];
  const dryDesc = { on: "只导航和识别，不点领取、照料、召唤", off: "会真的点领取、照料、召唤" };

  const t0 = Math.floor(now / 1000);
  const history = [
    { id: "ce64f0ad3586", module: "daily", source: "ws", status: "succeeded", started: t0 - 1820, duration: 22.97, dry_run: true },
    { id: "cbc145738a81", module: "daily", source: "ws", status: "stopped", started: t0 - 1890, duration: 1.71, dry_run: true },
    { id: "a91e02bb7c10", module: "daily", source: "schedule", status: "succeeded", started: t0 - 86400 + 320, duration: 31.4, dry_run: false },
    { id: "77d0c3e1f2a9", module: "daily", source: "schedule", status: "failed", started: t0 - 86400 - 7200, duration: 12.2, dry_run: false },
  ];

  const logs = [
    [t0 - 1843, "INFO", "api", "经 API 启动任务 daily（来源 ws，任务 ce64f0ad3586）"],
    [t0 - 1840, "INFO", "module.daily", "邮箱 11 封；当前屏：剩余6天，剩余6天，无限制，无限制"],
    [t0 - 1836, "INFO", "module.daily", "邮件：没有剩余不到 24 小时的邮件（已领 0 封）"],
    [t0 - 1829, "INFO", "module.daily", "精灵之森：企鹅巢穴 可领，精灵之泉 4:20:15，魔罗戈拉种植地 107:41:44；照料：1/3，12:05:29 后"],
    [t0 - 1828, "WARNING", "module.daily", "精灵之森：dry-run，会做：领取企鹅巢穴"],
    [t0 - 1821, "INFO", "module.daily", "誓约召唤：今天的免费召唤已经用完（账本）"],
    [t0 - 1820, "INFO", "runtime", "任务 daily 结束：succeeded，用时 23.0 秒"],
  ];

  // 单次收菜的模拟日志（点击后逐条出现）
  const script = [
    [300, "INFO", "api", "经 API 启动任务 daily（来源 gui）"],
    [900, "INFO", "scene", "场景：lobby"],
    [1500, "INFO", "module.daily", "邮箱 11 封；当前屏：剩余6天，剩余6天，无限制，无限制"],
    [2300, "INFO", "module.daily", "邮件：没有剩余不到 24 小时的邮件（已领 0 封）"],
    [3200, "INFO", "scene", "场景：sanctuary → daily_forest"],
    [4200, "INFO", "module.daily", "精灵之森：企鹅巢穴 可领，精灵之泉 4:20:15，魔罗戈拉种植地 107:41:44"],
    [4800, "WARNING", "module.daily", "精灵之森：dry-run，会做：领取企鹅巢穴"],
    [5600, "INFO", "module.daily", "誓约召唤：今天的免费召唤已经用完（账本）"],
    [6200, "INFO", "runtime", "任务 daily 结束：succeeded，用时 5.9 秒"],
  ];

  function pad(n) { return String(n).padStart(2, "0"); }
  function countdown(iso) {
    if (!iso) return null;
    let s = Math.max(0, Math.round((Date.parse(iso) - Date.now()) / 1000));
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    return `${h}:${pad(m)}:${pad(s)}`;
  }
  function clock(unix) {
    const d = new Date(unix * 1000);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  function when(unix) {
    const diff = Date.now() / 1000 - unix;
    if (diff < 3600) return `${Math.round(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.round(diff / 3600)} 小时前`;
    return `昨天 ${clock(unix).slice(0, 5)}`;
  }
  function localTime(iso) {
    const d = new Date(iso);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  const statusText = { succeeded: "成功", stopped: "急停", failed: "失败", running: "运行中", timeout: "超时", stuck: "卡死" };
  const sourceText = { ws: "手动", api: "手动", gui: "手动", schedule: "计划" };

  // 模拟一次任务：onLog(entry) 逐条回调，onDone(status) 结束；返回 stop()
  function simulateRun(onLog, onDone) {
    const timers = [];
    const start = Date.now() / 1000;
    script.forEach(([ms, lvl, src, msg], i) => {
      timers.push(setTimeout(() => {
        onLog([start + ms / 1000, lvl, src, msg]);
        if (i === script.length - 1) onDone("succeeded");
      }, ms));
    });
    return function stop() {
      timers.forEach(clearTimeout);
      onLog([Date.now() / 1000, "WARNING", "runtime", "任务 daily 结束：stopped（急停）"]);
      onDone("stopped");
    };
  }

  window.E7Mock = { status, modules, timers, fields, dryDesc, history, logs, countdown, clock, when, localTime,
    statusText, sourceText, simulateRun, nextRun: forest.toISOString() };
})();
