# 文档索引

| 文档 | 说明 |
| --- | --- |
| [项目 README](../README.md) | 功能、快速开始、配置、架构与 API 概览 |
| [开发文档](开发文档.txt) | 需求与整体设计原始文档（V1.2） |
| [账号与机器人接入](接入指南.md) | QQ 个人号 / 官方机器人 / 微信，扫码与回调配置 |
| [人设系统](人设系统.md) | 三级覆盖、Prompt 组装、风格参数与记忆联动 |
| [人设示例](人设示例.md) | 内置示例人设「小满」，可直接照着改 |
| [语音与生图](语音与生图.md) | TTS、云端生图的模型、音色与缓存配置 |
| [记忆与回复优化](记忆与回复优化.md) | 双层记忆、召回策略与回复节奏 |
| [主动推送](proactive_push.md) | 活力 Agent、私聊惦记与推送策略 |
| [后端说明](../backend/README.md) | 分层职责、本地启动、接口约定 |
| [前端说明](../frontend/README.md) | 开发构建、目录与代码约定 |
| [Windows 部署](../deploy/windows_pack/README.md) | 本地一键包使用说明 |
| [Docker 部署](../deploy/docker/README.md) | 服务器编排与持久化 |
| [语音通话桥](../deploy/voice_call/README.md) | 可选的本地 ASR / 通话运行环境 |

## 关键设计约定

1. **分层红线**：路由只做参数校验；业务全在 Service；数据库读写只在 Repository；
   平台协议只在 Adapter；配置只从 `config_loader` 读取。
2. **统一消息结构**：业务层只使用 `MessageSegment` / `MessagePayload`，
   平台差异由适配器翻译。
3. **降级优先**：Redis / Chroma / Edge-TTS / LLM 任一不可用时，
   系统自动降级而不是崩溃（对应开发文档第 10 章）。
4. **扩展钩子**：`backend/core/hooks.py` 预留消息、LLM、发送前后钩子，
   新插件无需改动分发主链路。
5. **记忆库分层**：`memory_service`（流程编排）、`memory_support`（冷热 / 重排 /
   Prompt 截断 / 缓存 / 熔断）、`memory_extractor`（LLM + 规则抽取）、
   `memory_maintenance`（衰减 / 去重 / 清理 / GC）、`memory_admin`（导出 / 统计），
   单文件均控制在 800 行以内，符合开发文档模块化约束。
