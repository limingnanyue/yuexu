# 部署目录

| 目录 | 场景 | 说明 |
| --- | --- | --- |
| `windows_pack/` | Windows 电脑或 x64 服务器 | 一键安装 / 启动 / 前端构建脚本；QQ 自动准备原生组件 |
| `docker/` | Linux x64 / arm64 服务器 | 独立服务器 Compose 支持 QQ 自动扫码；原 Compose 供已有协议服务使用 |

两个方案共用同一套 `config_example.yaml` 与 `.gitignore` 规则，敏感配置均不进入仓库。

Linux 后端也可直接用 Python 运行，QQ 登录环境仍由本机 Docker Engine 管理，步骤见 [Docker 部署说明](docker/README.md)。微信 ClawBot 无需安装额外协议组件；Gewechat 只兼容已有服务。
