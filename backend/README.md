# 后端（Python / FastAPI）

## 目录职责

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 入口 | `main.py` | 注册路由、生命周期、全局配置，无业务代码 |
| 依赖 | `dependencies.py` | 数据库会话、登录鉴权、权限、缓存/调度器注入 |
| 公共 | `common/` | 无业务逻辑：异常、日志、工具、消息结构、缓存、加密 |
| 核心 | `core/` | 配置加载、定时任务、账号状态、扩展钩子 |
| 数据 | `database/` | ORM 模型、引擎、初始化数据 |
| 仓储 | `repositories/` | 只做数据库 / 缓存读写 |
| 业务 | `services/` | 全部业务逻辑 |
| 适配 | `adapters/` | QQ / 微信协议差异隔离 |
| 路由 | `routers/` | 参数校验 + 调用 Service |

## 本地启动

```bash
# 项目根目录（yuexu/）
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-optional.txt
copy config_example.yaml config.yaml
python -m backend.main            # 或 uvicorn backend.main:app --reload
```

启动后访问：

- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/system/health
- 默认后台账号：配置文件 `security.admin`（默认 `admin / admin123`，请及时修改）

## 接口约定

- 成功：直接返回数据对象 / 列表，分页返回 `{items, total, page, page_size}`；
- 失败：非 2xx，body 为 `{"code": "...", "message": "...", "detail": ...}`；
- 鉴权：除 `/api/auth/login` 与 `/api/system/health` 外，均需 `Authorization: Bearer <token>`。

## 分层红线（详见开发文档第 12 章）

1. 路由层不写业务逻辑；
2. 所有数据库读写必须经过 `repositories/`；
3. 所有平台消息发送必须经过 `adapters/`；
4. 配置统一从 `core/config_loader.get_config()` 读取；
5. 外部调用（LLM / 搜索 / TTS / 适配器）必须捕获超时与异常并写日志。

## 记忆库模块拆分（4.5 优化版）

| 文件 | 职责 |
| --- | --- |
| `services/memory_service.py` | 业务编排：召回、写入、确认/否认、管理入口 |
| `services/memory_support.py` | 冷热分层、过滤重排、Prompt 截断、召回缓存、熔断/并发 |
| `services/memory_extractor.py` | LLM 摘要提纯 + 规则抽取 + 手动记忆 |
| `services/memory_maintenance.py` | 热度衰减、自动去重、冷记忆淘汰、向量 GC、索引重建 |
| `services/memory_admin.py` | 后台导出与统计 |
| `database/migrate.py` | 启动时自动补列 + 旧记忆回填（免手动迁移） |
| `core/background.py` | 回复后异步写入上下文 / 记忆，异常隔离与关闭收尾 |

约束：记忆子模块文件均 <800 行；召回读同步、写入异步；向量异常时自动降级关键词检索。

