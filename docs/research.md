# 调研记录（2026-10-13）

## 一、现有自动化脚本

| 项目 | 热度/更新 | 功能 | 技术 | 备注 |
|---|---|---|---|---|
| [Solunium/Epic-Seven-E7-Secret-Shop-Refresh](https://github.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh) | 139★ / 2026-04 | 刷神秘商店：天空石预算、实时计数、刷新历史 | Python，鼠标 + ADB 双模式 | ADB 模式必须 1920×1080 |
| [brunocordioli072/epic7_bot](https://github.com/brunocordioli072/epic7_bot)（PyPI epic7-bot） | 61★ / 2024-06 | 只完成了商店购买；讨伐、迷宫、自动机械塔、精灵祭坛、竞技场 NPC、日常都还停留在规划 | Python + OpenCV + ADB | 基本停更 |
| [purpxd/E7AutoShop](https://github.com/purpxd/E7AutoShop) | 49★ / 2025-07 | 刷商店 | PyQt5 + ADB + Tesseract | 1920×1080 |
| [Haolinc/Epic-Seven-Automation](https://github.com/Haolinc/Epic-Seven-Automation) | 2025-02 | 刷商店 + 竞技场 NPC（可用友情书签补旗） | OpenCV + ADB | 带设备选择启动器 |
| [gabrielmisato/Epic-Seven-Autobuy](https://github.com/gabrielmisato/Epic-Seven-Autobuy) | 新 | 刷商店；确认后才计数、已购跳过、失败自停、调试截图 | uiautomator2 + Tesseract | 在 MuMu 1600×900 下测试 |
| [Wrong-pixel/epic7auto](https://github.com/Wrong-pixel/epic7auto) | 2023，已停更 | **国服**刷商店 | ADB 连 MuMu | 国服里唯一的一个 |
| [leerogerstheman/e7-steam-bot](https://github.com/leerogerstheman/e7-steam-bot) | 新 | 刷关、商店、竞技场、圣域、派遣、召唤、日常串行、装备出售、弹窗处理；卡死检测、告警、录制回放、OCR | Steam/PC 端：DXGI + 归一化坐标 + 模板 JSON + 场景状态机 | **架构参考** |

**结论**
- 几乎所有项目都只做刷商店。
- 刷关和日常这一块是空白。
- 都用通用 adb 截图，分辨率写死。
- 都没有利用 MuMu 的 IPC 和 MuMuManager。

## 二、未来模块方向

**RTA BP 助手**
- [e7rtabot.com](https://e7rtabot.com/)：
  - Live Draft：逐步给出 AI 的 pick/ban 建议和实时胜率，可设置赛制、段位、战场规则、先后手。
  - Quick Analysis：输入双方阵容，预测胜负。
  - Hero Stats：胜率、选取率、前禁率、克制、协同、配装。
  - 后禁后的站位建议，以及账号赛季画像。
  - 模型覆盖约 120 个常用英雄，**所有英雄都要手动输入**。
- [SamTheCoder777/E7-RTA-Helper](https://github.com/SamTheCoder777/E7-RTA-Helper)：用 SIFT 识别屏幕上的英雄头像，自动读取 BP 局面，然后推荐英雄、预测胜率。
- 我们的切入点：已经有 MuMu 实时帧，**可以自动识别 BP 界面再叠加推荐**，并且全程只读。

**[e7.wiki](https://e7.wiki/)（国服社区站，v1.13.2）**
- 角色和神器图鉴、角色配装&简评。
- GVG 团战作业，可按进攻阵容检索。
- RTA 对局检索（国服 + 外服）。
- 混沌召唤推荐、节奏榜、装备模拟器、礼包氪金计算器、兑换码列表。
- [伤害计算器](https://calc.e7.wiki/)。

**配装**
- Fribbels Epic 7 Optimizer：截图识别装备并导入，然后做配装优化、装备评分、重铸预测。

**候选扩展模块**
- RTA BP 助手
- 装备扫描与导出（对接 Fribbels），低分装备辅助出售
- GVG 作业查询
- 兑换码提醒与兑换
- 资源统计曲线

## 三、MuMu 实测（B01）
- MuMu 6.6.4，目录结构为 `nx_main\`（MuMuManager.exe、adb.exe、sdk\external_renderer_ipc.dll），另有 `nx_device\12.0|15.0\shell\adb.exe`。
- `MuMuManager.exe info -v all` 输出 JSON。实例启动后会带上 `adb_host_ip` / `adb_port`（实例 0 为 16384）、`player_state`。
- IPC：`nemu_connect(根目录, index)`。截图为 RGBA 且上下颠倒，1600×900 下平均约 8ms（最快 3.4ms）。触控直接使用横屏坐标。
- `wm size` 返回的是竖屏物理尺寸 900x1600，所以不要用它判断分辨率。
- 导出函数中还有 `nemu_get_display_id`、`nemu_input_event_finger_touch_down/up`（多指）、`nemu_input_text`、按键事件。
