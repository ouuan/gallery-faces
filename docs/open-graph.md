# 链接分享（Open Graph）

在中文版「管理 → 设置 → 链接分享（Open Graph）」中，分别配置中文前端和日语只读前端，点击「保存设置」后立即生效，无需重启或重新构建。

| 设置 | 标签 | 留空时 |
| --- | --- | --- |
| 分享标题 | `og:title` | 使用站点标题 |
| 分享描述 | `og:description` | 不输出 |
| 预览图 URL | `og:image` | 不输出 |
| 站点 URL | `og:url` | 不输出 |

两个前端的字段独立，不互相回退。`og:type` 固定为 `website`，`og:site_name` 使用站点标题，`og:locale` 分别为 `zh_CN`、`ja_JP`。这是站点级分享卡片，同一前端的所有路由使用相同配置，不生成单张照片或单个帖子的卡片。

URL 必须是完整的 HTTP(S) 地址，不接受相对路径或含用户名、密码的地址。预览图需可供外部匿名访问；站点 URL 填写对应前端的公开地址，避免填入内部后端地址。完整卡片应填写站点 URL 和预览图 URL；未配置时不会自行挑选图库照片。标题最多 100 字符、描述最多 500 字符、URL 最多 2048 字符。

## HTML 与部署

中文版由后端在初始 HTML 中插入标签。日语版构建保留 SSI include 指令，附带的 Nginx 配置通过 `/api/v1/site/open-graph?locale=ja` 获取标签并在返回 HTML 前插入。两个入口均不依赖浏览器执行 JavaScript，HTML 禁止缓存；静态 assets 继续长期缓存。日语页的图片 CSP 不变，元数据不会使访客浏览器下载预览图。

升级时需要同时更新后端、中文前端和日语前端镜像。若自行托管 `dist-ja`，需启用 SSI 并代理 `/api`（参考 `deploy/nginx-ja.conf.template`）；普通静态托管或 `vite preview` 不会解析 SSI。中文 `dist` 应由项目后端提供。开发时 Vite 从 `API_PROXY_TARGET`（默认 `http://127.0.0.1:8000`）读取标签；后端离线时仍允许页面加载。

可直接检查部署入口的响应，不必打开浏览器：

```sh
curl -fsS https://your-gallery.example/ | rg 'og:'
curl -fsS https://your-japanese-gallery.example/posts | rg 'og:'
```

响应中应出现实际 `<meta property="og:…">` 标签，不能残留 `<!--open-graph-->` 或 `<!--# include … -->`。分享平台可能保留自己的卡片缓存；修改后可能需要在平台刷新抓取或等待缓存更新。

标签语义遵循 [Open Graph protocol](https://ogp.me/)。
