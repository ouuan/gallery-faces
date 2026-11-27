# Gallery Faces

自托管照片库，支持从 Instagram、X 和本地目录导入照片 / 持续监控，按人物浏览、审核人脸识别结果及整理重复图片。访客可直接浏览，管理操作需使用管理员密码。

## 部署

需要 Docker Compose。

1. 复制配置并创建导入目录：

   ```sh
   cp .env.example .env
   mkdir -p imports
   ```

2. 编辑 `.env`：

   - `ADMIN_PASSWORD`：设置强随机管理员密码。
   - `IMPORT_PATH`：本地导入目录，默认 `./imports`；确保容器用户 UID 10001 可读取目录和文件。
   - `COOKIE_SECURE`：默认 `true`，通过 HTTPS 反向代理访问。仅在本机使用 HTTP 时改为 `false`。
   - `WORKER_CONCURRENCY`：图片处理并发数，默认 `auto`，按可用 CPU 自动选择，最多 4；也可设为正整数，内存紧张时建议设为 1。
   - `REQUEST_RATE_PER_SECOND` / `REQUEST_GLOBAL_RATE_PER_SECOND` / `REQUEST_MAX_CONCURRENCY`：每 IP 请求速率、全局请求速率及并发请求上限，默认 10 / 50 / 64。
   - `FEEDBACK_RATE_LIMIT_PER_MINUTE` / `FEEDBACK_RATE_LIMIT_PER_DAY`：每个 IP 在滚动 60 秒 / 24 小时内的反馈提交上限，默认 5 / 50，须为正整数；跨图片累计，共享出口 IP 的访客共享额度。
   - `FORWARDED_ALLOW_IPS`：可信反向代理的 IP 或 CIDR，逗号分隔，默认 `127.0.0.1,::1`。Docker 中需按实际网络填写，可能为宿主机网关地址。代理须正确设置或追加 `X-Forwarded-For`，多层代理须配置完整可信链；不要信任不可信客户端所在网段或 `*`，否则可能被伪造请求头绕过限流。未配置时，额度将按代理地址累计。

3. 启动服务并下载人脸识别模型（约 191 MB，首次部署需要联网；使用 CPU，无需 GPU）：

   ```sh
   docker compose build
   docker compose up -d web
   docker compose run --rm worker python -m app.worker --install-models
   docker compose up -d worker
   ```

服务默认监听 `127.0.0.1:8000`。本机访问 <http://localhost:8000>；对外访问时，将 HTTPS 反向代理指向该地址。修改 `.env` 后运行 `docker compose up -d` 使配置生效。

照片、数据库和模型保存在 `gallery-data` 数据卷中。

可选的本地磁盘清理、独立挂载、公开图片缓存和 Cloudflare 配置见[缓存部署指南](docs/deployment-cache.md)。

可另行构建部署[日语只读帖子前端](docs/japanese-frontend.md)，与中文版共享后端。

管理员设置中可分别配置中日文前端的[链接分享卡片（Open Graph）](docs/open-graph.md)。

中文图库的导航可打开「每日一图」「随机图片」，或进入两种支持单人及多人对战的游戏：「认脸游戏」辨认照片中的人物，「史官测验」看全图猜最早来源日期，单人看平均偏差，多人则由每题猜得最接近的玩家平分 1 分。窄屏可从顶栏菜单进入；右上角的 RSS 图标可订阅当前筛选结果。

在管理员设置中保存 Agent 审核规则后，可从「识别审核」导出离线图片审核包。导入返回的 JSON 或 ZIP 后，管理员在建议队列中决定是否应用；导入本身不会修改图库。

## 备份与恢复

升级前先备份。为保证照片与数据库一致，备份和恢复时均需停止服务。

```sh
mkdir -p backups
docker compose stop web worker
docker run --rm \
  -v gallery-faces_gallery-data:/data \
  -v "$PWD/backups:/backup" \
  -v "$PWD/scripts:/scripts:ro" \
  python:3.14-slim python /scripts/backup.py backup /backup/gallery.tar.gz --data /data
docker compose start web worker
```

卷名随 Compose 项目名变化，执行前用 `docker volume ls` 确认并替换 `gallery-faces_gallery-data`。备份含平台 cookies，请妥善保管。

恢复时，将命令中的 `backup.py backup` 改为 `backup.py restore`，并将 `/data` 挂载到一个空数据卷。恢复完成后让 web 和 worker 使用该卷，再启动服务。

## 本地开发

需要 Python 3.12–3.14、uv、Node.js 22.12+ 和 pnpm 12.21.0。以下三个终端均从项目根目录开始。

启动后端：

```sh
cd backend
uv sync --frozen
DATA_DIR=../data IMPORT_DIR=../imports ADMIN_PASSWORD=dev-password COOKIE_SECURE=false \
  uv run uvicorn app.main:app --reload
```

另开终端，安装模型并启动任务处理进程：

```sh
cd backend
DATA_DIR=../data uv run python -m app.worker --install-models
DATA_DIR=../data IMPORT_DIR=../imports uv run python -m app.worker
```

另开终端启动前端：

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm run dev
```

访问 <http://localhost:5173>，管理员密码为 `dev-password`。前端将 API 请求代理到后端的 8000 端口；API 文档位于 <http://localhost:8000/docs>。

测试与构建（从项目根目录执行）：

```sh
cd backend
uv run pytest
cd ../frontend
pnpm run test
pnpm run build
```

修改 API 后，重新生成接口类型：

```sh
cd backend
uv run python -c 'import json; from app.main import app; from pathlib import Path; Path("../docs/openapi.json").write_text(json.dumps(app.openapi(), indent=2))'
cd ../frontend
pnpm run types
```

端到端测试需先启动后端和前端，将后端管理员密码设为 `test-password`，并使用独立空白 `DATA_DIR`（如 `../data-e2e`）。测试会写入数据。

```sh
cd frontend
pnpm exec playwright install chromium
pnpm run test:e2e
```
