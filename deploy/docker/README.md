# Docker Compose 部署（Linux 服务器）

## QQ 自动扫码：服务器方案

适用于 **Linux x64 / arm64 + 本机 Docker Engine + Compose v2**。后端可以在容器或宿主机 Python 中运行，QQ 登录组件按账号运行在独立容器中；无需服务器图形界面，二维码显示在访问控制台的浏览器中。Windows x64 服务器使用 [Windows 启动包](../windows_pack/README.md)。

下面的 `docker-compose.server.yml` 是完整配置，单独使用 `-f` 启动，不与原 `docker-compose.yml` 叠加。两个配置使用同一 backend 容器名，不能同时启动。

```bash
cd deploy/docker

# 仅首次准备，已有配置请保留
cp ../../config_example.yaml ./config.yaml
cp .env.example .env
mkdir -p data logs static
vim ./config.yaml

# 保持 app.port: 8000、redis.enabled: false，修改 jwt_secret 和初始管理员密码
docker info
docker compose -f docker-compose.server.yml config --quiet
docker compose -f docker-compose.server.yml up -d --build
docker compose -f docker-compose.server.yml logs -f backend
```

访问 `http://服务器IP:8000`，在「QQ 个人账号」保留「自动配置，只需扫码」。首次拉取固定版本镜像，后续复用本机缓存；中断会有限重试并复用 Docker 已缓存层。准备完成后手机扫码、确认即可。微信 ClawBot 也可直接扫码，无需 NapCat。

后端与受管 QQ 容器均使用 host 网络，因此回调、OneBot 和 WebUI 走宿主机 `127.0.0.1`，无需开放 QQ 组件端口。`app.port` 必须与 Compose 的 `--port 8000` 一致；改端口时同步修改启动命令和 Dockerfile 健康检查。host 网络的行为见 [Docker 官方说明](https://docs.docker.com/engine/network/drivers/host/)。

服务器配置不启用 Redis，默认进程内缓存可直接运行；若自行启用 Redis，使用宿主机可达的 Redis 地址，不能使用原 bridge 方案的服务名 `redis`。保持单进程、单 worker 运行。

此配置把 `/var/run/docker.sock` 挂入后端，以创建和停止账号容器；这等价于授予后端管理本机 Docker 的能力，应由可信管理员部署和管理控制台。QQ 容器本身不挂此 socket，也不开启 privileged。参见 [Docker daemon 权限说明](https://docs.docker.com/engine/security/#docker-daemon-attack-surface)。不要通过 `chmod 666` 或开放无鉴权 Docker TCP 接口解决权限问题。

### 镜像下载慢或失败

- 为 **Docker daemon** 配置可信的 registry mirror 或代理；仅给月叙设置 `HTTPS_PROXY` 不能代理 Docker 拉取。代理配置见 [Docker 官方说明](https://docs.docker.com/engine/daemon/proxy/)。
- 也可由管理员把同一镜像同步到自己的镜像仓库，在 `.env` 设置 `YUEXU_NAPCAT_IMAGE` 后重建 backend；建议保留固定 digest。默认镜像为 `mlikiowa/napcat-docker:v4.18.41@sha256:b101b8968cc31ae428ec0f8e117386e4ced7773b2d8226ed9f7ddfcec55f1b7e`。
- 私有仓库需要认证时，由管理员先执行 `docker login` 和 `docker pull` 将镜像缓存到本机。月叙不会读取 Docker CLI 保存的登录凭据。
- 无法联网时，在**相同目标架构**且可以联网的 Docker 主机准备完整镜像：

```bash
docker pull mlikiowa/napcat-docker:v4.18.41@sha256:b101b8968cc31ae428ec0f8e117386e4ced7773b2d8226ed9f7ddfcec55f1b7e
docker tag mlikiowa/napcat-docker:v4.18.41@sha256:b101b8968cc31ae428ec0f8e117386e4ced7773b2d8226ed9f7ddfcec55f1b7e mlikiowa/napcat-docker:v4.18.41
docker save -o napcat-v4.18.41.tar mlikiowa/napcat-docker:v4.18.41
```

将文件传到服务器，在服务器执行：

```bash
docker load -i napcat-v4.18.41.tar
# 在 deploy/docker/.env 加入下面一行，显式信任已导入的本地 tag
# YUEXU_NAPCAT_IMAGE=mlikiowa/napcat-docker:v4.18.41
docker compose -f docker-compose.server.yml up -d --force-recreate backend
```

`docker save/load` 后可能只保留 tag，默认 digest 仍会触发联网查找，因此离线导入需显式指定该 tag。自定义仓库和本地 tag 由管理员保证来源与版本；自动流程不会把固定 digest 静默降级为 tag。以上只处理 QQ 组件，首次构建后端所需的基础镜像和依赖仍需联网或预先准备。

若后台保存已把 `config.yaml` 的 `adapters.napcat.docker.image` 写为具体值，环境变量不会覆盖该值；离线导入或换源时直接修改此项，或恢复 `${YUEXU_NAPCAT_IMAGE:-默认镜像}` 占位符后再使用 `.env`。

### 宿主机 Python 运行

同样需要本机 Docker Engine；用启动月叙的用户执行 `docker info`，确认有权访问 socket。项目根目录运行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config_example.yaml config.yaml
# 修改 jwt_secret 和管理员密码；保持 app.port: 8000、redis.enabled: false
cd frontend
npm install
npm run build
cd ..
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

无需安装 Docker Python SDK 或额外 QQ 程序。默认连接 `/var/run/docker.sock`；非默认 socket 可在启动进程环境设置 `YUEXU_DOCKER_SOCKET`。宿主机 Python 不会自动读取 Compose 的 `.env`，镜像等环境变量应在服务管理器或当前 shell 设置。rootless Docker 的 host 网络不能保证与宿主机共享 loopback，当前自动模式按常规 Linux Docker Engine 部署；其它容器平台继续使用「连接已有 NapCat」。

### 数据和更新

| 位置 | 内容 |
| --- | --- |
| `./data`、`./logs`、`./static` | 后端数据库、运行日志和静态缓存 |
| `./config.yaml` | 可写配置，保留后台保存的设置 |
| `./data/adapters/napcat/` | 账号端口、凭据、实例归属；与数据库一起备份 |
| Docker `yuexu-napcat-…` 命名数据卷 | 各账号的 QQ 登录数据、NapCat 配置和插件；备份时也要保留 |

断开或删除连接会停止对应容器，保留数据卷。不要清理 `yuexu-napcat-…` 数据卷或 `.docker-owner` 文件来修复下载问题，以免丢失登录状态。固定组件版本不会自动追新。

```bash
git pull
docker compose -f docker-compose.server.yml up -d --build
curl http://127.0.0.1:8000/api/system/health
```

## 连接已有协议服务：原 bridge 方案

保留给已部署 NapCat / Gewechat 服务或只使用官方机器人、ClawBot 的环境。此方案未挂载 Docker socket，不支持自动创建受管 QQ 容器；QQ 请选「连接已有 NapCat」。

### 步骤

```bash
cd deploy/docker

# 1. 准备配置文件（禁止把 config.yaml 提交到仓库）
cp ../../config_example.yaml ./config.yaml
vim ./config.yaml

# 2. 准备环境变量
cp .env.example .env
vim .env

# 3. 启动
docker compose up -d --build

# 4. 查看日志 / 健康状态
docker compose logs -f backend
curl http://127.0.0.1:8000/api/system/health
```

访问 `http://服务器IP:8000` 进入控制台，`/docs` 查看接口文档。

### 配置要点

1. `redis.enabled` 改为 `true`，`redis.url` 使用 `redis://redis:6379/0`；
2. `security.jwt_secret` 换成随机长字符串；
3. 如需 PostgreSQL：启用 compose 中的 `postgres` 服务，并把
   `database.url` 改为 `postgresql+asyncpg://yuexu:change-me@postgres:5432/yuexu`，
   同时安装可选依赖 `asyncpg`（Dockerfile 中追加
   `pip install -r requirements-optional.txt`）；
4. 语音 / 向量记忆依赖 `edge-tts` 与 `chromadb`，需要时在 Dockerfile 中安装可选依赖；
5. `frontend/dist` 由多阶段构建自动生成，无需单独部署 Nginx；
   若需要 Nginx 托管，可自行在 `frontend/dist` 前加一层反向代理。

### 数据持久化

| 宿主机目录 | 容器目录 | 说明 |
| --- | --- | --- |
| `./data` | `/app/data` | SQLite 数据库、Chroma、备份 |
| `./logs` | `/app/logs` | 运行日志 |
| `./static` | `/app/static` | 表情、语音缓存、二维码临时文件 |
| `./config.yaml` | `/app/config.yaml` | 配置文件（只读挂载） |

### 更新

```bash
git pull
docker compose up -d --build
```
