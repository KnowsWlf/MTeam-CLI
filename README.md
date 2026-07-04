# mteam-cli

一个基于 **Python + Playwright** 的 M-Team 全能命令行工具。它有两副面孔：

- 🤖 **无人值守保活** —— 多账户每日自动登录，解决「连续 40 天不登录删号」。登录用 TOTP 全自动完成，**无需扫码、无人工**。
- 🧠 **AI 友好的数据源** —— 把账户统计、种子搜索/详情、做种/下载、公告，以**干净的结构化数据**（JSON/YAML/CSV…）吐出，可直接喂 LLM、接进 Agent，或在终端配合 `jq` 使用。（H&R / 站内信因 M-Team 启用请求签名，仅网页端可用。）

> 它原本是一个单文件脚本，现已重构为分层的 `mteam_cli` 包。

---

## 安装

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium          # 仅保活（login/run/schedule/inspect）需要

cp config.toml.template config.toml && vi config.toml

mteam-cli doctor                     # 自检：账户/通知/路径/调度（不依赖 playwright）
```

`python -m mteam_cli <cmd>` 与 `mteam-cli <cmd>` 等价。

---

## 用法一：保活自动化（浏览器登录）

```bash
mteam-cli login              # 对默认账户做一次登录（--account 指定其他账户）
mteam-cli run                # 立即对所有账户跑一轮保活（--account 限定单个）
mteam-cli schedule           # 常驻：每账户每天在随机时刻自动保活（容器默认命令）
mteam-cli inspect --login    # DOM 变动时抓取登录页快照排查
```

`schedule` 为每个可保活账户各自挑一个 `[schedule].window` 窗口内的随机时刻，到点先抖动 10–300s 再登录；失败只记日志不退出；每小时一条心跳。保活流程：优先用每账户的 localStorage 快照（跳过 2FA），失败则回退「账号密码 + TOTP」，并拦截 `/api/member/profile` 确认成功。

## 用法二：数据查询（API Key，喂给 AI / Agent）

每个数据命令支持 `--account <用户名>`（默认第一个账户）和 `-f/--format`：`table`（默认）/ `json` / `yaml` / `csv` / `md` / `plain`。**`json`/`yaml`/`csv` 是 pipe-clean 的**（无横幅、诊断走 stderr），可安全管道给 `jq` 或喂给 LLM。

```bash
mteam-cli profile                      # 账户详情与统计（上传/下载/魔力/分享率）
mteam-cli search 关键词 -n 20           # 搜索种子（--category/--mode 可选）
mteam-cli detail <种子ID> --dl-token    # 种子详情（可选生成下载链接）
mteam-cli seeding                      # 当前做种（--leeching 改看下载中）
mteam-cli hnr                          # H&R 记录（网页端专用：启用请求签名，CLI 不支持）
mteam-cli messages                     # 站内信（网页端专用：启用请求签名，CLI 不支持）
mteam-cli notices                      # 站点公告
mteam-cli digest                       # 预览当天高分新片（IMDB 高分影视）

# 接进 AI
mteam-cli profile -f json | llm "用要点总结我的 M-Team 账号状态"
mteam-cli search 4K -f json | jq '.[].title'
```

> 数据查询走 M-Team 官方 API（默认 `api.m-team.cc`，`x-api-key` 鉴权），不依赖浏览器。API Key 在 M-Team 控制台「实验室」生成。可用 `[site].api_base_url` 切换到 `api.m-team.io`。

---

## 配置（`config.toml`）

配置是 **TOML 文件**。发现顺序：`--config PATH` > `MTEAM_CONFIG` 环境变量 > `./config.toml`。复制 `config.toml.template` 为 `config.toml` 填写即可。每个账户是一个 `[[account]]` 块；**保活**需 `username`+`password`+`totp_secret`，**数据查询**需 `api_key`，两套独立可只配其一。

```toml
[smtp]                      # SMTP 服务器全局共享（收件人在各账户里）
host = "smtp.qq.com"
from = "me@qq.com"          # 纯邮箱，勿带显示名（否则 QQ/Foxmail 502）
password = "授权码"

[digest]                    # 高分/热门新片摘要全局默认
min_imdb = 8.0              # 影视用 IMDB 阈值
min_seeders = 30            # music/adult 无 IMDB，用做种数（热度）阈值
types = ["movie", "tvshow"]

[[account]]
username = "user1"
password = "pass1"
totp_secret = "totp1"
api_key = "apikey1"
digest_enabled = true       # 该账户签到通知附当天新片精选
  [account.notify]          # 各渠道 opt-in；都留空 = 不发通知
  telegram_token = ""
  telegram_chat_id = ""
  smtp_to = "me@foxmail.com"
  [account.digest]          # 可选：只写想覆盖的键，其余继承 [digest]
  types = ["music"]
```

完整字段见 `config.toml.template`。Telegram 需先给 Bot 发消息再取 chat_id；SMTP 密码用授权码，465 用 SSL/587 用 STARTTLS。

**密钥可用环境变量覆盖**（便于 CI/k8s 注入、明文不入镜像）：账户 i（按 `[[account]]` 顺序，1-based）的 `MTEAM_PASSWORD_i`/`MTEAM_TOTP_SECRET_i`/`MTEAM_API_KEY_i`，以及全局 `NOTIFY_SMTP_PASSWORD`——env 非空则盖过 TOML 同名值。

---

## Docker / Kubernetes

```bash
cp config.toml.template config.toml && vi config.toml   # compose 把它挂到 /app/config.toml
docker compose up -d            # 单容器跑 schedule，data 卷持久化每账户登录态
docker compose logs -f
```

镜像 `knowswlf/mteam-cli`，基于 `mcr.microsoft.com/playwright/python`（自带 Chromium + 中文字体），`TZ=Asia/Shanghai`。容器内可随时手动触发：`docker exec mteam-cli mteam-cli run` / `mteam-cli profile -f json`。

K8s 用 **StatefulSet**（登录态有状态、单持有者），清单见 [`kubernetes-manifests/statefulset.yaml`](kubernetes-manifests/statefulset.yaml)。

---

## 架构

分层（依赖只向下），详见 [`CLAUDE.md`](CLAUDE.md)：

```
src/mteam_cli/
  ├── core/         Settings(多账户) + logging + models + BrowserSession
  ├── api/          数据接口：x-api-key 纯 HTTP（不依赖 Playwright）
  ├── automation/   保活：localstorage + login(密码+TOTP) + runner
  ├── notify/       Telegram + SMTP + 飞书（按账户独立 + 并发 + 错误隔离）
  ├── scheduler/    DailyScheduler（每账户一个 job）
  └── cli/          argparse 分发 + 每命令一模块 + emit/table/account 助手
```

**关键约束**：保活必须走浏览器登录（API 访问不计入 40 天活跃），数据与保活两套传输严格分离。

---

## 免责声明

本项目仅供学习与个人使用，请遵守 M-Team 的使用规则。数据命令仅访问你自己账号的数据；保活用单账号、固定随机抖动，目的是保持账号活跃，不鼓励刷分或绕过平台规则。
