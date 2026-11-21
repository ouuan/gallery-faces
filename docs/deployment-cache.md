# 图片缓存与 Cloudflare 部署

公开图片使用 `/api/v1/media/by-hash/{variant}/{digest}`，variant 为 `image`、`thumbnail` 或 `original`，digest 为对应文件实际字节的 SHA-256（64 位小写十六进制）。图库列表和详情返回 `image_url`、`thumbnail_url`、`download_url`；`image_id` 继续用于反馈和管理。

## 源站策略

### 本地磁盘缓存（默认不清理）

在 `.env` 同时设置 `MEDIA_CACHE_LOW_FREE_GIB=5` 和 `MEDIA_CACHE_TARGET_FREE_GIB=10` 后重新部署 worker。它每分钟检查实际文件系统：某盘可用空间低于 5 GiB 时，只从该盘清到 10 GiB。GiB 可用小数，目标必须大于低水位。清空两个值可停止淘汰，已淘汰的文件仍可按需恢复。

`/data`、`/data/images`、`/data/originals` 可分别挂载。例如在 **web 和 worker 的 volumes 都**保留 `gallery-data:/data`，再添加 `/mnt/display:/data/images` 和 `/mnt/source:/data/originals`。既有图库先停服务、迁移文件并确认容器用户有读写权限，避免新挂载遮住旧文件。备份容器也须使用相同挂载；还原时先解包到空目录，再将各子目录放回对应挂载。同一 `st_dev` 的目录共享水位；不同设备独立计算。若只有数据库所在盘紧张而该盘没有可清理图片，只记录告警。

`MEDIA_CACHE_MIN_IDLE_HOURS` 设置文件可被清理前的最短闲置小时数，默认 24，支持小数。设为 0 可取消近期使用保护；正在读取的文件仍不删，缩略图永久保留。修改后需重新部署 worker。

同盘时，展示图按闲置天数的 4 倍排序；原图按闲置天数乘以 0.25 至 1 的权重，最新来源帖发布至今 0–30 天线性递增，超过 30 天权重为 1。无日期则按首次导入时间。列表访问和 CDN 命中不会刷新源站使用时间。

展示图优先从原图重新生成；需要找回原图时先查挂载导入副本，再尝试来源单帖，只接受 SHA-256 匹配的文件。**启用清理意味着允许删除仅有远端来源的原图，原帖失效后可能无法找回。缓存不是备份。** 下载最多等待原图恢复 10 秒。失败、等待超时或处于退避期时，优先提供现存展示图；没有展示图则返回不缓存的 `503` 和 `Retry-After`。等待超时不会取消后台任务，下次访问同一链接仍可获得找回的原图。

所有来源尝试完毕仍找不到匹配原图，才累计一次失败。重试由访问触发，间隔从 1 分钟起逐次翻倍。连续 12 次失败后（最早 34 小时 7 分钟）标记「已丢失」，停止自动找回；此时公开预览与下载优先取现存展示图，没有则取缩略图。失败未解决期间不再淘汰现存展示图。请求等待超时、磁盘满或数据库忙不计入丢失阈值。成功找回、重新导入匹配文件或从回收站成功恢复会清除失败状态。管理面板单列已丢失的原图，不与已淘汰、意外缺失重复统计。

管理员在「设置 → 图片磁盘缓存」可只读查看 worker 最近上报的配置、各盘可用空间及两种文件的当前张数。未进入回收站的图片才参与统计；非主动淘汰的缺失文件单列，无法读取目录时显示未核实。每块盘只保留最近一次低空间清理的结果；最低分与最短闲置天数仅统计实际删除的文件，未删除时没有阈值。升级前的清理不追溯。

面板按分钟汇总最近 24 小时的源站缓存读取，展示图和原图分别计算。命中率为直接读取次数 ÷（命中次数 + 未命中次数）；文件缺失或已标记淘汰算未命中，同一次读取在恢复后重试不重复计数。成功恢复按实际重新写入的文件计数，不含失败尝试或仅校验已有文件。统计含后台任务读取，不含缩略图及浏览器或 CDN 直接响应的请求；数据库写入繁忙时可能漏记读取，以免影响图片访问。数据从升级后开始积累，重启保留。

### HTTP 缓存

| 资源 | Cache-Control | Cloudflare-CDN-Cache-Control |
| --- | --- | --- |
| 成功的 hash 图片与 Vite `/assets/` 文件 | public, max-age=31536000, immutable | 遵循 Cache-Control |
| SPA HTML 与前端路由回退 | no-store | no-store |
| 其他 API、旧 ID 图片、后台/参考图、错误响应 | no-store | 错误响应显式 no-store |

hash 图片支持 ETag、条件请求、HEAD 和 Range。源站先检查公开条件和文件存在性，再决定是否返回 304。If-None-Match 优先于 If-Modified-Since，支持弱 ETag、列表和 `*`。公开响应不因管理员 cookie 改变。原图作为附件返回，保留存储文件名；`download=true` 也可将展示图或缩略图作为附件下载。降级使用不缓存的 `307` 跳转，不会在原 hash 下缓存其他字节。若重建的 JPEG 字节改变，旧 hash 也不会返回新内容。对于非主动淘汰的意外缺失，沿用旧规则：下载 URL 指向展示图，原图 hash URL 返回 404。

隐藏、删除或取消公开状态会立即影响图库和源站访问。已经缓存在浏览器或 CDN 的旧直链可能继续有效一年；不调用 Cloudflare 自动清理 API。一年是允许的缓存有效期，边缘节点可能提前淘汰缓存。

## 批量 ZIP 下载

照片库的「多选下载」支持全选已加载照片，每次最多 200 组；每组下载当前公开代表图，采用与单图下载相同的降级规则，并使用实际文件的扩展名。切换筛选或排序会清空选择，加载更多和切换布局保留选择。

前端先向 `POST /api/v1/gallery/downloads` 提交 `{"group_ids":[1,2]}`，检查公开状态及文件可用性，再将返回的下载链接交给浏览器。`GET /api/v1/gallery/download.zip?groups=1,2` 会再次检查，逐块生成 ZIP64 兼容的 ZIP；不创建临时压缩包，不在前端缓冲整个文件。图片使用 ZIP 的存储模式，不重复压缩。归档内文件名加组编号前缀，避免重名覆盖。

ZIP 响应不缓存，并设置 `X-Accel-Buffering: no`。反向代理应保留流式响应，避免缓冲整个下载。响应不预计算总长度，不支持 Range／断点续传；传输中断需重新下载，浏览器可能无法显示总大小或百分比。

## Cloudflare Cache Rules

在应用域名上创建两条互斥规则（将 `gallery.example.com` 替换为实际域名）：

1. **公开静态资源**：表达式 `(http.host eq "gallery.example.com" and (starts_with(http.request.uri.path, "/assets/") or starts_with(http.request.uri.path, "/api/v1/media/by-hash/")))`。Cache eligibility 选 **Eligible for cache**；Edge TTL 选遵循源站 Cache-Control、缺少该响应头时绕过缓存；Browser TTL 选 **Respect origin**。
2. **其余请求**：表达式 `(http.host eq "gallery.example.com" and not (starts_with(http.request.uri.path, "/assets/") or starts_with(http.request.uri.path, "/api/v1/media/by-hash/")))`。Cache eligibility 选 **Bypass cache**。

保留完整查询字符串缓存键，尤其不能忽略 `download=true`。不要配置按管理员 cookie 绕过公开资源，也不要覆盖源站 TTL 或错误响应缓存策略。检查并移除冲突的旧 Page Rules、Cache Rules 和 Browser Cache TTL 覆盖。不要把存储目录作为静态目录公开。

图片 URL 无扩展名，需显式配置缓存资格；默认扩展名缓存规则不足以覆盖它们。参考 [Cloudflare 默认缓存行为](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/) 和 [Cache Rules 设置](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/)。

## 升级与检查

升级前按现有流程备份数据库和图片目录。启动时幂等添加展示图 hash、缩略图 hash、原图文件名和非唯一 hash 索引。首次升级分批扫描既有派生文件，不重新编码；每 100 条记录提交一次。扫描完成前启动不会接收请求，大图库需要预留磁盘读取和启动时间。中断后重启会保留已提交字段并继续，完成的 hash 不重复计算。

缺失或不可读的文件会记录日志，未完成字段会在后续启动重试。图库对缺失派生文件或未完成 hash 使用旧 ID URL（no-store）；文件确实缺失时返回 404。不要原地修改已发布文件；若运维工具替换派生文件，必须同步更新对应 hash，不能继续在旧 hash URL 下提供新字节。导入流程会保存实际输出 hash。

部署后使用同一完整 URL 连续请求公开图片，确认 Cache-Control、ETag 和 Cloudflare `CF-Cache-Status: HIT`（首次可能 MISS），并在浏览器开发者工具确认后续访问直接复用缓存。分别检查普通展示和附件下载、登录前后访问、条件请求和 Range。确认图库、管理、参考图和错误响应不命中 CDN 缓存，HTML 使用 no-store 且 CDN 不存储，以便立即输出最新分享设置。隐藏或删除后直接访问源站应拒绝，已有边缘缓存可能仍可访问。
