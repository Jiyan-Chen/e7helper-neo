import { describe, expect, it } from "vitest";
import { ago, dayTime, formatDuration, formatElapsed, toDate } from "./time";

describe("toDate", () => {
  it("三种格式都能解析", () => {
    const unix = toDate(1792300000)!;
    const iso = toDate(new Date(1792300000 * 1000).toISOString())!;
    expect(unix.getTime()).toBe(iso.getTime());
    // 模块 history.jsonl 的不带时区本地时间
    const local = toDate("2026-10-15T01:17:43")!;
    expect([local.getHours(), local.getMinutes(), local.getSeconds()]).toEqual([1, 17, 43]);
    expect(toDate(null)).toBeNull();
    expect(toDate("坏的")).toBeNull();
  });
});

describe("格式化", () => {
  it("倒计时超过 100 小时照样显示小时", () => {
    expect(formatDuration(149 * 3600 + 5 * 60 + 6)).toBe("149:05:06");
    expect(formatDuration(-3)).toBe("0:00:00");
  });

  it("任务用时", () => {
    expect(formatElapsed(5.94)).toBe("5.9 秒");
    expect(formatElapsed(23)).toBe("23 秒");
    expect(formatElapsed(129)).toBe("2 分 9 秒");
    expect(formatElapsed(null)).toBe("—");
  });

  it("今天 / 明天 / 昨天", () => {
    const now = new Date(2026, 9, 18, 15, 0, 0);
    const at = (d: number, h: number) => new Date(2026, 9, d, h, 5).getTime() / 1000;
    expect(dayTime(at(18, 9), now)).toBe("今天 09:05");
    expect(dayTime(at(19, 3), now)).toBe("明天 03:05");
    expect(dayTime(at(17, 13), now)).toBe("昨天 13:05");
    expect(dayTime(at(15, 1), now)).toBe("10月15日 01:05");
    expect(ago(now.getTime() / 1000 - 30, now.getTime())).toBe("刚刚");
    expect(ago(now.getTime() / 1000 - 600, now.getTime())).toBe("10 分钟前");
  });
});
