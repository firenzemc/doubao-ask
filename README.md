# doubao-ask

豆包问答自动化服务：基于 [opencli](https://github.com/jackwener/opencli) 驱动真实浏览器里的豆包网页版，返回**回答全文 + 引用链接**。同时暴露 HTTP API 与 MCP（streamable HTTP）两种接口。

## 接口

| 接口 | 说明 |
| --- | --- |
| `POST /ask` | 提问。Body: `{"question": "...", "timeout": 120}` → `{"answer": "...", "citations": [{"name","url"}], "elapsed_ms": n}` |
| `POST /mcp` | MCP streamable HTTP 端点，工具 `doubao_ask(question, timeout?)` |
| `GET /health` | 存活探针（vinyard 健康门用，秒回） |
| `GET /status` | 诊断：opencli 桥接状态 + 豆包登录态（`logged_in`） |
| `GET /setup/screenshot` | 容器内浏览器截图（PNG），用于扫码登录/排障 |
| `POST /setup/eval` | 在容器浏览器页面执行 JS（`{"js": "..."}`，设置/兜底用） |

MCP 客户端配置示例：

```json
{ "mcpServers": { "doubao": { "type": "http", "url": "http://100.109.44.79:42180/mcp" } } }
```

## 速率限制（防反爬）

豆包有反爬验证（滑块/captcha），触发后所有提问被拒。**本服务强制节流**：

- 所有请求串行执行（单浏览器会话），排队超 300s 返回 429（带 `Retry-After`）。
- 两次提问的最小间隔默认 **30s**（`RATE_MIN_INTERVAL_S` 环境变量可调，改大更安全）。
- 适配器内引用点击也已减速（900ms/次），避免合成点击突发。
- 调用方请自行再加一层节奏控制（批量任务建议 ≥1 问/分钟）。

若返回 `Doubao blocked the request with a verification challenge`：说明触发验证。
等 10–30 分钟冷却再试；持续不解则用 `/setup/screenshot` 看页面、用 `/setup/eval` 手动过验证。

## 反爬纪律（血的教训，务必遵守）

豆包对 Linux/数据中心浏览器环境本身就判高风险；账号被风控后所有环境（本机+容器）
同时拒答。2026-07-20 已实战踩坑一次（高频测试 → 账号级验证码）。因此：

- **提问频率**：硬性上限 5 问/分钟（本服务默认更严：30s/问）。批量任务建议 ≤1 问/分钟。
- **适配器内所有点击**：随机 1–3s 间隔、坐标在元素内随机偏移（永不点正中心）。
- **禁止**任何绕过节流的做法（并行会话、缩短间隔、连发重试）。
- 触发验证码后：在常用浏览器里手动过一次滑块（账号级解除），冷却 ≥30 分钟再恢复自动化。

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
无 baked secrets。`vinyard.toml` 声明 `class="service"`（注册进 `/api/services`、删除保护）、
port 路由（`public_port=42180`）、api+mcp 两个 faces、
named volume `doubao-chrome-profile` 持久化登录态、`pinned=true`。

```bash
# 常规迭代：改代码 → push → redeploy（登录态在 volume 里，不受影响）
curl -X POST http://100.109.44.79/api/projects/doubao-ask/redeploy
```

## 首次登录 / 重新登录 runbook

豆包 session 会过期（经验值数天到数周）。`/status` 返回 `logged_in: false` 时按此恢复：

1. 打开登录页（容器浏览器）：
   ```bash
   curl -X POST http://100.109.44.79:42180/setup/eval \
     -H 'Content-Type: application/json' \
     -d '{"js":"location.href=\"https://www.doubao.com/chat\""}'
   ```
   等 ~10s，然后点登录按钮：
   ```bash
   curl -X POST http://100.109.44.79:42180/setup/eval \
     -H 'Content-Type: application/json' \
     -d '{"js":"[...document.querySelectorAll(\"button, [role=button], div, span\")].find(e=>e.textContent.trim()===\"登录\"&&e.offsetParent)?.click(); \"ok\""}'
   ```
2. 取截图看二维码：`open http://100.109.44.79:42180/setup/screenshot`。
3. 用手机豆包 App / 飞书扫码确认登录。
4. 等 ~10s 后复查：`curl http://100.109.44.79:42180/status` → `logged_in: true`。
5. 登录态写入 named volume，容器重启/重建都保留；无需重新扫码除非 session 过期。

备选：若二维码流程异常，用 `/setup/eval` 直接操作 DOM（如切换短信登录、点按钮）。

## 运维备忘

- 超时：`timeout` 是豆包生成等待上限（默认 120s），长回答调大；API 侧另有 90s 进程余量。
- 无引用属正常：豆包未联网搜索的回答没有引用标记，`citations` 为 `[]`。
- 重建后首次 `/ask` 较慢（浏览器冷启动 + daemon 启动），属预期。
- 容器日志（含 chromium/xvfb 输出）：`vin logs doubao-ask` 或 `GET /api/projects/doubao-ask/logs`。
