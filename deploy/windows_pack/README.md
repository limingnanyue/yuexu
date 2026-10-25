# 月叙 · Windows 本地一键启动包

> 适用：Windows 10/11 或具备相同运行环境的 Windows x64 服务器，已安装 Python 3.11+（3.12 推荐）与 Node.js 18+（仅首次构建前端需要）。QQ 自动组件需要 x64。

## 首次使用

1. 双击 `install.bat`
   - 自动创建 `.venv` 虚拟环境并安装后端依赖
   - 自动从 `config_example.yaml` 生成 `config.yaml`
   - 按提示选择是否安装可选依赖（edge-tts / chromadb）
2. 编辑项目根目录 `config.yaml`
   - 填写 `security.jwt_secret`（随机长字符串）
   - 按需填写 `search.api_key`、`llm` 相关配置（模型也可在后台配置）
3. 双击 `start.bat`
   - 启动后端并自动打开浏览器 `http://127.0.0.1:8000`
   - 默认后台账号：`admin / admin123`（登录后立即修改）

## 构建前端

开发调试：

```bat
cd frontend
npm install
npm run dev
```

生产打包（生成 `frontend/dist`，由后端自动托管）：

```bat
build_frontend.bat
```

## 目录说明

| 文件 | 说明 |
| --- | --- |
| `install.bat` | 安装依赖、生成配置文件 |
| `start.bat` | 启动服务并打开控制台 |
| `build_frontend.bat` | 构建前端静态资源 |

## 常见问题

- **端口被占用**：修改 `config.yaml` 的 `app.port`，并同步修改 `start.bat` 中的 `--port`。
- **依赖下载慢**：`install.bat` 已默认使用清华镜像；如需官方源可自行修改。
- **语音不可用**：执行 `.venv\Scripts\pip install edge-tts`，未安装时会自动降级为文字。
- **记忆检索降级**：未安装 `chromadb` 时自动使用关键词检索，功能可用但语义召回较弱。
- **QQ 个人号自动扫码**：在账号页选择「QQ 个人账号 → 自动配置，只需扫码」。Windows x64 可自动下载、校验并启动独立 NapCat，无需预装 QQ 或 Docker；首次约下载 124 MB。下载失败会有限重试，符合续传条件时保留断点；可点击「重新准备」，退出程序会停止自身启动的进程并保留登录数据。
- **QQ 组件下载慢**：可在启动月叙的进程环境设置 `HTTPS_PROXY`，或在 `config.yaml` 的 `adapters.napcat.download_urls` 填写可信 HTTPS 完整包地址列表，失败后回退官方源。离线包使用 `adapters.napcat.offline_archive`，仍需通过固定版本 SHA256。详细示例见[接入指南](../../docs/接入指南.md#下载加速与离线包)。
- **Windows 服务器**：更新代码后重新运行 `install.bat`、`build_frontend.bat` 并重启 `start.bat`，保留 `config.yaml`、`data` 等已有数据。远程访问时用 `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000` 启动，端口需与 `config.yaml` 的 `app.port` 一致；浏览器打开服务器地址即可扫码。Linux 服务器见[服务器部署](../docker/README.md)。
- **已有 NapCat 未启动**：选择「连接已有 NapCat」的账号仍需先启动自己的协议端。
- **微信个人号 / Gewechat**：上游已停止维护，当前仅保留已有可用服务的兼容接入；微信 ClawBot 可直接扫码，但仅支持私聊文本。

> 本项目仅供个人学习测试，请勿使用主号、禁止商用与对外提供服务。
