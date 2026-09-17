# CAIN 导航首页

保留静态 HTML 首页与现有样式。项目内容由独立管理后台维护，发布后生成完整 HTML；访客无需调用管理 API。代码更新仍通过 GitHub Actions 构建、部署 Docker 镜像。

## 管理项目

地址：`https://cjw32.xyz/navigation-admin/`，账号 `admin`。

首次部署或重设密码时，在服务器终端执行（密码隐藏输入，不放进 Git 或聊天）：

```sh
docker exec -it cjw-navigation-page-admin-1 python /app/admin/set_password.py
```

密码至少 12 位。更新密码会退出全部旧会话；后台没有公开注册/初始化入口。

1. 登录后新增或选择项目，填写名称、简介、HTTPS 地址或站内路径。
2. 上传封面（JPG/PNG/WebP，≤15 MiB）与可选视频（MP4/WebM，≤40 MiB）。
3. 用上下箭头排序，可隐藏或从草稿移除项目。
4. 保存并预览，确认后点击“发布到首页”。修改草稿不会提前改变公开首页。

封面生成适合卡片的 JPEG。视频保留原文件，生成前 12 秒、720px 宽、20fps、无音轨 H.264 预览。请把希望展示的片段放在上传视频开头。素材按内容哈希命名并长效缓存，更新时使用新地址，因此不会被旧缓存覆盖。

首页先显示封面；页面加载完成后逐个预取接近可视区域的短视频，悬停会优先下载当前卡片。播放真正开始才淡入，失败或缓冲时保留封面。短暂划过不触发播放，离开即暂停。同页再次悬停复用已下载内容；触屏、减少动态效果偏好不自动播放，省流量模式不后台预取。

## 部署与数据

- `web`：Nginx，宿主机仅绑定 `127.0.0.1:18080`，内存上限 96 MiB。
- `admin`：Python 标准库 + SQLite + FFmpeg，内部 8080，不开放宿主机端口，384 MiB / 0.75 CPU。
- 数据目录：`/opt/cjw-sites/navigation-page/data/admin`，不随镜像更新删除。
- `content.sqlite3`：草稿、已发布内容、版本、会话与媒体索引。
- `auth.json`：私有密码校验信息（600），不得提交或公开。
- `originals/`：原上传文件，仅服务账号可读；`incoming/`：临时处理文件。
- `public/index.html`：当前公开静态首页；`public/media/`：处理后的公开媒体。
- `backups/published-*.json`：每次发布前的项目内容；`backups/deploy-*.sqlite3`：代码部署前的 SQLite 在线备份。

删除项目不会删除素材，备份和原文件目前不自动清理。目录应纳入服务器备份；长期使用时关注剩余磁盘。后台重启会用当前模板与持久化的已发布内容重新生成首页。代码中的 `admin/seed.json` 只用于首次初始化，后续项目请通过后台管理。

CI 运行测试与密钥检查，分别构建 web/admin 镜像，用 digest 部署。失败恢复上一应用版本。回滚不会清除业务数据；若需恢复历史项目内容，管理员应先备份现有 SQLite，再从私有 JSON 备份恢复为草稿、预览并发布，勿直接覆盖在线数据库。

首次拉取过慢时，可从相同构建的 GHCR digest 下载完整 OCI 镜像，中转至服务器并校验包摘要后导入。确认 `images.env` 中的两个精确 digest 均可被 `docker image inspect` 找到，再运行对应 release 的 `bash deploy.sh cjw260 --offline`。离线模式仅跳过登录和下载，仍校验镜像来源及 digest、使用部署锁、备份数据、检查健康并保留回滚。不要用随意打的本地标签代替发布清单，也不要并行启动两个发布进程。

反向代理需要允许 `/navigation-admin/` 请求和至少 40 MiB 请求体，上传/转码等待至少 120 秒。后台路由禁止索引、要求登录和同源 CSRF 校验；公开媒体支持缓存和 Range 请求。

## 本地验证

```sh
node --test tests/previews.test.mjs
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 deploy/check-secrets.py
```

Python 需要 3.10+；安装 FFmpeg/FFprobe 后，测试会覆盖真实媒体转换。测试仅使用临时数据和合成测试凭证，不连接生产数据库。
