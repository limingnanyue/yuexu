# 月叙的偶然惦记

实现入口：`backend/services/proactive_push_service.py`。复用已有 SQLAlchemy 会话、账号适配器、人设、模型和 `MemoryRepo`，没有额外依赖。轮询使用独立数据库会话；机会与发送 claim 在调用模型前提交，发送前重新核对用户消息版本和开关。每次最多发送一位用户。

- `await ProactivePushService(session).poll()`：仅私聊；所有来源至少距上次用户消息 6 小时。先记忆，再 6～24 小时 idle，最后离线至少 3 天的 fallback。
- 每轮对话的 idle 时间在 6～24 小时内随机，25% 只抽一次。记忆关联机会也是 25%，同一条记忆、场景与对话周期只抽一次。当前记忆抽签失败就结束本次轮询；后续轮询可以检查独立的 idle/fallback 机会。
- fallback 首次进入条件后安排未来 0～24 小时的随机机会，10% 抽一次，失败也等 7 天。成功发出后全部来源冷却 7 天。
- 每用户、每机器人当日最多 2 条，自然周（周一开始）最多 3 条；首条和接话按实际气泡分别计数。仅 `sent=true` 计数，失败和校验拒绝留存为 `sent=false`。
- 记忆或 idle 首条成功后，如果日周配额允许，复用 `next_idle_at` 持久化一个 10～30 分钟后的接话机会。仅当前周期最新的 pending 首条可接话一次，接话不继续接话；用户回复、停用、发送失败或超过首条发出 30 分钟都不补发。fallback 保留 7 天冷却，不安排接话。
- `await service.observe_message(event)`：私聊回复结束前一周期，清除忽略数和休眠；返回非空字符串时由消息链路被动回复开关确认。`不要主动发消息`、`/push off` 关闭后，普通回复不会重新开启；用户可用 `/push on` 或 `重新开启主动消息` 开启。
- 回复只归属于上次入站消息之后最新的一条已发出推送；更早的忽略记录保留原状态，避免抬高历史回复率。上次入站时间未知时也只更新最新一条。
- `await service.mark_read(bot_id, user_id, message_id, at=known_read_time)`：接可信已读回执，调用方正常提交会话。只有发出满 12 小时、确实已读且没有回复才算忽略；连续两次休眠 7 天。没有回执的平台保持 pending。

模型沿用账号当前人设，单次调用专用 `PUSH_PROMPT`，每次只输出一条聊天气泡，可有最多两个自然短句和轻松问句。提示同时提供当前机器人与用户的最近 6 条成功私聊、最多 3 条未被否认的私聊记忆，以及接话时上次主动消息和实际经过的分钟数；群聊、其他用户和其他机器人资料不混入。参考数据与系统指令分开，不凭空编造经历或等候时间。

首条优先从最近话题的一个具体细节或关联记忆切入，没有依据时才轻轻表达惦记。接话补充相关想法或自然收尾，不重复开场、反复问“在不在”，不卖惨催回复；亲近程度沿用已有对话，不突然升级关系。对方近期说忙、累或不想聊时给出空间，也不把一次情绪当成长期状态。

QQ 个人账号可自动分享配图：在「AI 生图」保存有效配置并启用后，私聊惦记和活力 Agent 的原有聊天模型会结合话题与用户喜好，决定是否生成一张风景、美食、小物等图片，无需发送 `/image`；普通文字也可不配图。图片由 AI 生成，不冒充实拍。两条流程各自保留原有频次；生图失败回退文字，不重试；生成期间收到用户新消息或停推时取消发送。自动生图会向所配置的服务商发送图片描述，可能产生费用；活力 Agent 的预览不调用生图。

账号或全局记忆关闭时，记忆触发和提示记忆均不读取；账号或全局上下文关闭时，不读取私聊历史、不追加缓存上下文。成功发送及持久记录提交后，向当前私聊上下文追加一条真实助手发言，让用户回复后能接上前文；失败消息和冻结会话不追加，缓存故障只记录警告，不改变已发送结果或重试。写缓存前重新读取最新会话，保留发送期间新来的对话。

不发送模型降级话术，也不重试生成或发送。超过 40 字、超过两个短句、换行、分点、超过一个表情、固定早晚安、客服话术、鸡汤或强迫回复均整条丢弃。首条仍保留原来的 6～24 小时随机机会与 25% 概率，不会因新增接话而变成每隔几分钟发送。

接话与上条主动消息相比，去掉标点、空白和符号后文字相同，也整条拒发，留存失败原因且不重新生成或追加上下文。这是文字去重，不判断换一种说法的语义重复。

## 后台与接入

后台“私聊惦记”可查看用户开关、日周频次、忽略数、休眠时间和消息反馈记录。管理员只能关闭推送；重新开启必须由用户在私聊中明确提出。

- `GET /api/push-tasks/users`：分页查询用户状态。
- `GET /api/push-tasks/records`：分页查询推送及反馈留存。
- `PUT /api/push-tasks/users/{bot_id}/{user_id}`：传入 `{"user_push_switch": false}` 停止推送。
- `POST /api/push-tasks/feedback/read`：由受信任的适配器或管理端提交 `bot_id`、`user_id`、`message_id` 和可选的 `read_at`，需要管理员认证。当前无可信已读回执的平台不调用此接口。

用户回复终止当前周期后，旧周期的迟到已读回执不会重新累计忽略或触发休眠。旧固定任务在启动时停用并保留归档，群聊欢迎、离群通知和手工主动发送入口也已拦截。

## 记忆匹配 demo

`memory_scene_match` 是可直接运行的简单规则示例。生产检索先经 `MemoryRepo` 隔离到当前私聊；只接受喜好、计划、心愿与在意事项。明确日期支持未来 0～3 天，未写年份支持跨年；季节使用当前月份。天气仅接受调用方已有的场景，不联网猜测。

在项目目录运行 Python：

```python
from datetime import datetime
from types import SimpleNamespace
from backend.services.proactive_push_service import memory_scene_match

at = datetime(2026, 10, 23, 16)
memory = SimpleNamespace(
    memory_type="preference", category="preference",
    content="我喜欢秋天看枫叶", tag_keywords=["秋天"],
)
assert memory_scene_match(memory, at) == "season:2026:秋"

memory.memory_type = "plan"
memory.content = "我计划2026年10月25日去考试"
assert memory_scene_match(memory, at) == "date:2026-10-25"

memory.memory_type = "preference"
memory.content = "我喜欢下雨天听爵士乐"
assert memory_scene_match(memory, at) is None
assert memory_scene_match(memory, at, {"weather": "下雨"})
```

验证：`.venv/Scripts/python.exe -m unittest backend.tests.proactive_push_test backend.tests.proactive_integration_test`。测试使用内存 SQLite 和假模型、假适配器，覆盖自然问句、上下文隔离、接话时序、用户回复取消、失败不重试及日周上限，不发送真实消息。
