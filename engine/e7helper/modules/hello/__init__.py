"""示例模块：演示模块契约的最小写法，可作为新模块的模板。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from e7helper.modules.base import TaskModule


class HelloConfig(BaseModel):
    greeting: str = Field("你好，第七史诗", description="打印的问候语", title="问候语")
    screenshots: int = Field(1, ge=1, le=10, description="截图次数", title="截图次数")


class HelloModule(TaskModule):
    id = "hello"
    name = "示例模块"
    description = "截图并打印分辨率，用于验证模块发现与设备连接"
    config_model = HelloConfig

    def run(self) -> None:
        cfg: HelloConfig = self.config
        self.log.info(cfg.greeting)
        for i in range(cfg.screenshots):
            if self.stopped:
                self.log.info("收到停止信号")
                return
            if self.ctx.controller is not None:
                # 经 Runtime 启动：用 ctl 截图并识别场景（截图会发布帧事件、参与卡死检测）
                state = self.ctl.detect()
                frame = self.ctl.last_frame
                self.log.info("第 %d 张截图：%dx%d，场景：%s", i + 1, frame.shape[1], frame.shape[0], state)
            else:
                frame = self.device.screenshot()
                self.log.info("第 %d 张截图：%dx%d", i + 1, frame.shape[1], frame.shape[0])
