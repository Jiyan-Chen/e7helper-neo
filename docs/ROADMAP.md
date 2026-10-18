# ROADMAP

状态：⬜ 待办 · 🔵 进行中 · 🟡 待审核 · ✅ 已通过

| 块 | 状态 | 内容 | 验收标准 | 审核记录 |
|---|---|---|---|---|
| B01 骨架 + 模块契约 + MuMu 设备层 | ✅ | 跟踪文档；uv 工程；`Module` 契约与自动发现（附 `hello` 示例）；`Device` 接口；MuMuManager / nemu IPC / adb 后备；CLI `doctor` / `bench` / `screenshot` / `tap` / `modules` / `run` | `doctor` 列出实例并连上；`bench` 给出 IPC 与 adb 截图耗时；截图为正确的 1600×900；示例模块被自动发现；pytest 通过 | [B01](reviews/B01.md) |
| B02 视觉层 + 模板工具 | ✅ | matcher（基准缩放、region、阈值、多尺度）、按模块分目录的 template_store（png + json）、RapidOCR（简中、数字）、CLI `capture`（框选采集并回验分数） | fixtures 截图上的模板识别和 OCR 测试通过 | [B02](reviews/B02.md) |
| B03 运行时 + 事件总线 + 场景/弹窗 | ✅ | runner（task 互斥、急停、超时、卡死检测、失败时保存调试截图）、帧订阅事件（供 assistant 使用）、scenes / popups、随机延迟和点击偏移 | 场景识别正确；常见弹窗能自动关闭 | [B03](reviews/B03.md) |
| B04 刷神秘商店 | ✅ | 天空石和金币预算、确认后才计数、已购跳过、连续失败自停、统计 | dry-run 决策正确；实跑 3 次刷新 | [B04](reviews/B04.md) |
| B05 竞技场 NPC | ✅ | 自动挑战 NPC（优先快速对战），可选用友情点数补旗 | 实跑 1–2 场 | [B05](reviews/B05.md) |
| B06 重复刷关/讨伐/迷宫 | ✅ | 在游戏自带的重复战斗基础上处理结算、体力不足、背包满，支持次数和体力上限（实际：托管战斗结算/重开 + 手动刷讨伐；异界、迷宫不做） | 实跑一轮小次数 | [B06](reviews/B06.md) |
| B07 日常收取 | ✅ | 圣域、派遣、免费召唤、公会捐献、邮件，按天记录（实际：邮件（只领快过期的）、精灵之森（领取 + 照料）、誓约免费召唤；派遣、骑士团不做） | 各项单独实跑 | [B07](reviews/B07.md) |
| B08 API 层 | ✅ | FastAPI 核心路由 + 模块子路由自注册 + WebSocket（日志、状态、帧、统计）；任务定时调度（按间隔反复启动模块，例如 `repeat_battle` 只开托管时周期结算重开，B06 用户确认） | 接口测试；能用 WS 控制任务启停 | [B08](reviews/B08.md) |
| B09 GUI | ✅ | Tauri 2 + React + TS + Vite + Tailwind + shadcn/ui；外壳 + 模块注册表 + JSON Schema 自动表单 + 日志、统计、模板采集页 | `pnpm tauri dev` 全流程可用 | [B09](reviews/B09.md) |
| B10 打包发布 | ⬜ | PyInstaller sidecar + Tauri 安装包 | 在干净环境装好后能跑 | |
| B11+ 扩展模块 | ⬜ | 英雄数据库（core/data）→ RTA BP 助手（assistant）→ 装备扫描 → GVG 作业查询 → 兑换码 → 资源统计 | 每个模块单独立项和审核 | |
