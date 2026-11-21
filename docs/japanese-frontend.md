# 日语帖子前端

日语版只读，以 X / Instagram 官方 embed 展示单列帖子时间线，不提供管理、反馈、图片下载或 footer。语言在构建时确定，不提供语言切换。

## 构建

在 `frontend` 目录运行 `pnpm build` 生成中文版 `dist`，运行 `pnpm build:ja` 生成日语版 `dist-ja`。开发使用 `pnpm dev:ja`。两个目录可独立发布，部署时将 `/api` 反向代理到升级后的同一个后端，SPA 路由回退到 `index.html`。日语版还须启用 SSI，在初始 HTML 中插入[可配置的 Open Graph 分享信息](open-graph.md)；附带 Nginx 配置已启用，普通静态托管不会解析这些标签。

## Docker Compose

既有中文服务和 worker 保持原配置。额外启动日语服务：

```sh
docker compose --profile ja build web-ja
docker compose --profile ja up -d web worker web-ja
```

日语入口为 `http://127.0.0.1:8001`，中文入口为 `http://127.0.0.1:8000`。分别配置 HTTPS 域名反向代理即可同时部署。只公开日语站时，仅对外代理 8001，中文版仍可用于内部管理。

日语镜像不包含数据库、worker 或后端。`BACKEND_URL` 默认 `http://web:8000`，可以设置为另一台机器的后端地址（包含协议和端口，不带末尾斜杠或路径）。后端仍须单独运行并升级；外部反向代理和后端可信代理配置沿用主部署文档。

单独构建或运行：

```sh
docker build --target japanese -t gallery-faces-ja .
docker run --rm -p 127.0.0.1:8001:80 \
  -e BACKEND_URL=http://your-backend:8000 gallery-faces-ja
```

CI 发布 `ghcr.io/ouuan/gallery-faces-ja`，版本标签与中文版一致。

## 名称与筛选

中文管理界面的人物、分组编辑中可填写日语名称，留空使用原名。快捷创建人物或分组后，可在人物管理中补充日语名。站点标题使用现有站点设置。

帖子查询使用 `/api/v1/posts`，分页前按平台帖子 ID 去重。同一帖子多张图只展示一次，同图不同帖子分别展示。人物筛选沿用公开代表图身份；“全員”要求所选人物在同一张代表图中同框，“選んだ人だけ”还会排除其他已识别人物，但允许未知人物。日期区间包含起点、不含终点。默认排除没有检测到人脸的图片。

日语 UI 用语统一为：帖子「投稿」、发布者「投稿者」、照片中的人物「写真に写っている人物」、筛选「絞り込み」。未登记数据使用「登録されていません」，搜索无结果使用「見つかりません」。

## embed 与图片边界

日语页不访问服务器图片、头像或下载接口，帖子响应不包含媒体地址。顶层 CSP 的 `img-src data:` 允许现有内联 SVG favicon，仍禁止从本站或外站 URL 加载图片；媒体加载被禁止，frame 仅允许官方 embed。帖子媒体由平台的跨域 frame 自行加载，不经过本站代理。embed 失败只显示提示、重试和原帖链接，不使用图片回退。

这是前端展示边界，并不是后端访问控制：共享后端仍保留中文版所需的图片和管理 API。不要把日语入口视为接口隔离网关。

平台可能因帖子删除、隐私设置、禁用嵌入、网络或浏览器设置而无法展示；平台 frame 的内部文案及 Instagram 外观由平台决定。网站自身 UI 使用日语，帖子原文不翻译。

## 验证

```sh
cd frontend
pnpm build:ja
pnpm exec playwright test --config playwright-ja.config.ts
```

专用浏览器测试使用受控的平台脚本和跨域 frame，检查手机/桌面布局、失败重试与不请求本地图片，不依赖平台的实时可用性。
