# doubao-ask

豆包问答自动化 HTTP 服务：基于 [opencli](https://github.com/jackwener/opencli) 驱动真实浏览器里的豆包网页版，返回**回答全文 + 引用链接**。

## API

| Endpoint | 说明 |
| --- | --- |
| `POST /ask` | 提问。Body: `{"question": "...", "timeout": 120}` → `{"answer": "...", "citations": [{"name","url"}], "elapsed_ms": n}` |
| `GET /health` | 存活探针（vinyard 健康门用，秒回） |
| `GET /status` | 诊断：opencli 桥接状态 + 豆包登录态（`logged_in`） |
| `GET /setup/screenshot` | 容器内浏览器截图（PNG），用于扫码登录 |
| `POST /setup/eval` | 在容器浏览器页面执行 JS（`{"js": "..."}`，设置/兜底用） |

所有请求串行执行（单浏览器会话）；排队超过 300s 返回 429。

## 工作原理

- `opencli doubao ask-cited`（自定义 adapter，`opencli-clis/doubao/ask-cited.js`）：
  开新对话 → 发问 → DOM 轮询等回答完成 → 拦截 `window.open` 后逐一点击行内引用标记
  （`span.container-DEV3jt`）收集真实来源 URL。
- 豆包回答里的引用**不是** `<a href>`，而是站点名 span，点击时经 JS 调 `window.open` 跳转，
  所以用 stub 收集；无引用的回答返回空数组。
- ⚠️ `container-DEV3jt` 是豆包前端的哈希 CSS 类名。若引用提取突然变空，重新侦察该类名
  （在本机 Chrome 里对引用标记 hover/click 调试即可）。

## 本地开发

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --port 8787   # 需要本机 opencli + 已登录豆包的 Chrome
```

## 部署（vinyard）

仓库满足 vinyard 部署契约：根 `Dockerfile`（multi-arch）、监听 `$PORT`、`/health`、
无 baked secrets。`vinyard.toml` 声明 port 路由（`public_port=42180`）、
named volume `doubao-chrome-profile` 持久化登录态、`pinned=true`。

```bash
curl -X POST http://100.109.44.79/api/deploy \
  -H 'Content-Type: application/json' \
  -d '{"name":"doubao-ask","source":{"repo":"<this repo url>","ref":"main"}}'
```

## 首次登录 / 重新登录 runbook

豆包 session 会过期（经验值数天到数周）。`/status` 返回 `logged_in: false` 时按此恢复：

1. 打开登录页（容器浏览器）：
   ```bash
   curl -X POST http://100.109.44.79:42180/setup/eval \
     -H 'Content-Type: application/json' \
     -d '{"js":"location.href=\"https://www.doubao.com/chat\""}'
   ```
2. 取截图看二维码：`open http://100.109.44.79:42180/setup/screenshot`
   （或 curl 存成 png 打开）。页面上出现登录二维码。
3. 用手机豆包 App / 抖音扫码确认登录。
4. 等 ~10s 后复查：`curl http://100.109.44.79:42180/status` → `logged_in: true`。
5. 登录态写入 named volume，容器重启/重建都保留；无需重新扫码除非 session 过期。

备选：若二维码流程异常，用 `/setup/eval` 直接操作 DOM（如切换短信登录、点按钮）。

## 运维备忘

- 单实例串行：并发请求会排队；批量调用方请自行控制节奏。
- 超时：`timeout` 是豆包生成等待上限（默认 120s），长回答调大；API 侧另有 90s 进程余量。
- 无引用属正常：豆包未联网搜索的回答没有引用标记，`citations` 为 `[]`。
- 重建后首次 `/ask` 较慢（浏览器冷启动 + daemon 启动），属预期。
