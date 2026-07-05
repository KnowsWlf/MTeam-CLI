# 会话交接 — 2026-07-05

一个超长会话的交接。目的：让新 Session 无缝接手后续任务。**不复述**已在 commit/spec/plan/memory 里的内容——只给状态、索引、待办、坑。

---

## 当前状态（一句话）

三件事本会话已全部完成并发布：**0.5.0**（digest 方案 B）、**Docker Hub 换账户 bitwild→knowswlf**、**0.6.0 配置迁移 env→TOML**。仓库在 `main`、工作树干净、`v0.6.0` 已推、CI 已构建 `knowswlf/mteam-cli:0.6.0`。**唯一未完成的是用户侧的 K3S 部署 apply**（清单已备好并验证，尚未 `kubectl apply`）。

---

## 已完成（带引用，勿重述）

1. **0.5.0 — digest 按类型质量信号（方案 B）**：music/adult 无 IMDB → 用 `status.seeders` 阈值；影视仍用 imdb。分桶排序。设计见 `docs/superpowers/specs/2026-06-21-digest-per-account-isolation-design.md` §方案B（0.5.0 已实现段）。已发布 `v0.5.0`。
2. **Docker Hub 账户 bitwild → knowswlf**：CI/compose/k8s/README/scripts 全改。用户已更新 GitHub Secrets `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`。CI 实证推到新账户成功。
3. **0.6.0 — 配置迁移 env → TOML**：
   - 设计：`docs/superpowers/specs/2026-07-04-toml-config-migration-design.md`
   - 计划：`docs/superpowers/plans/2026-07-04-toml-config-migration.md`（6 任务 TDD，全部完成）
   - 合并提交 `1d39fe0`（`Merge feat/toml-config`），分支已删，`v0.6.0` tag 已推，CI 构建通过。
   - 要点：`Settings.from_toml(path)` 唯一入口；`--config` > `MTEAM_CONFIG` > `ROOT_DIR/config.toml`；混合式 env 覆盖密钥（`_env_secret`）；删了 `from_env` + 整套扁平解析辅助；值对象与下游零改动。含 brooks-review 修复（账户块结构校验、password strip 注记），提交 `961c628`。

配置细节现已是权威文档：`CLAUDE.md` 的 “Configuration (TOML)” 段 + `config.toml.template`。

---

## 待办 / 可接手的线索

按优先级：

1. **（用户侧）应用 K3S 部署** — 清单已备好并用真实 `from_toml` 验证解析成 2 账户无误，但**尚未 apply**：
   - 位置：`/data/Workspace/K3S-Cluster/default/mteam-cli/{config.yaml,statefulset.yaml}`（该目录非 git 仓库；**含明文密钥，勿复制进本仓库或任何 git**）。
   - 顺序：`kubectl apply -f config.yaml` → `kubectl apply -f statefulset.yaml` → `kubectl logs -f mteam-cli-0`。先 Secret 后 StatefulSet，否则新 Pod 无 config crashloop。
   - 详见记忆 `deployment-k3s-toml.md`。
2. **riddd 账户 `api_key` 是占位值 `"dd"`**（无效）：保活不受影响（用 password+totp），但其数据查询会失败；digest 已关故无碍。想让 riddd 也能查数据，在 config.yaml 换真实 key 后 rollout restart。
3. **CI Node.js 20 弃用告警**（非紧急）：`docker-publish.yml` 里 actions（checkout@v4 等）被强制跑在 Node 24（已有 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`）。彻底消除需升级 action 大版本。
4. **潜在代码增强（未做，非承诺）**：混合式 env 覆盖只支持 `password`/`totp_secret`/`api_key`/`smtp password`，**不支持 `telegram_token`/`feishu_token`**。因此含 TG token 的配置在 k8s 上只能整份 config.toml 进 Secret（当前采用的方案），无法用 ConfigMap+env 拆分保护 TG token。若未来想支持，需在 `_parse_accounts_toml` 给 notify token 加 env 覆盖。

---

## 关键约束 / 坑（新 Session 必读）

- **发布走单 tag 推送**：一次推 >3 个 tag，GitHub 不触发 CI。`git push origin main` 后单独 `git push origin vX.Y.Z`。详见记忆 `mteam-release-process.md`。
- **推送/CI 走 SSH**，此沙箱到 `github.com:22` 常超时 → push 需用户本机执行（`! git push ...`）；查 CI 用 `gh`（HTTPS 可通）：`gh run list` / `gh run watch <id>`。
- **保活必须浏览器登录**，勿改成 API ping（40 天不活跃删号）。
- **`[smtp].from` 必须纯邮箱**（无显示名），否则 QQ/Foxmail 502。见 CLAUDE.md Critical constraints。
- **subPath Secret 挂载不热更新**：改 config.toml 后须 `kubectl rollout restart statefulset/mteam-cli`。
- **0.6.0 起无 config 会 fail-fast**（有意）：CLI 找不到 config.toml 直接清晰报错退出。

---

## 项目记忆（已写入，新 Session 会自动加载）

`/home/liuxiaohui/.claude/projects/-data-Workspace-MTeam-CLI/memory/`：
- `deployment-k3s-toml.md` — K3S 部署、config.toml Secret 挂载、rollout restart、knowswlf 账户
- `mteam-release-process.md` — 单 tag 推送、>3 tag 不触发、gh 查 CI

---

## Suggested skills（新 Session 按任务调用）

- **finishing-a-development-branch** — 若接手做了新分支改动，收尾合并/打 tag。
- **brooks-review** — 配置/部署这类改动合并前审一遍（本会话对 0.5.0/0.6.0 都审过，风格可参照）。
- **test-driven-development** — 本项目所有配置/逻辑改动均 TDD（`tests/test_config_toml.py` 是 TOML 解析的样板）。
- **writing-plans** / **brainstorming** — 若接手待办 #4（notify token env 覆盖）这类新功能，先设计后实现（本会话既有节奏：brainstorm→design doc→plan→TDD→review→finish）。
- **verification-before-completion** — 部署类变更用真实 `Settings.from_toml` 解析验证（本会话用 `yaml.safe_load` 提取 + `from_toml` 解析确认 2 账户，是可复用的验证手法）。

---

## 复现验证（新 Session 落地前自检）

```bash
cd /data/Workspace/MTeam-CLI
python -m pytest tests/ -q          # 应 71 passed
python -c "import mteam_cli; print(mteam_cli.__version__)"   # 0.6.0
git log --oneline -1                # 1d39fe0 Merge feat/toml-config ...（若已推则 origin/main 同步）
```
