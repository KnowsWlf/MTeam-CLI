# 高分新片摘要（High-Score Digest）设计

**日期**：2026-06-05
**状态**：已确认，待实现

## 目标

在每日签到通知中，附上当天发布的高分影视资源摘要（默认 IMDB ≥ 8.0、过去 24 小时内发布的电影/电视剧）。同时提供一个独立的 `mteam-cli digest` 命令，可随时手动预览、调参。

## 背景与决策

- **数据源 = search API**（不用 RSS）。M-Team 的 `/torrent/search` 每条结果已自带 `imdbRating` / `doubanRating` / `createdDate` / `category`，过滤所需数据全现成；复用已有的 `search_torrents()` + `api_post`，零新传输层。RSS 多数不含 IMDB 评分，拿到后还需逐条回查详情，更绕且引入新依赖。
- **fetch-once**：高分新片是全站统一内容。一轮调度里**只拉一次**（用第一个 `can_query` 账户的 api_key），缓存为文本，拼进每个**开启了开关**的账户签到通知。避免重复请求，也解决"保活-only 账户没有 api_key 拉不了"的问题。
- **不碰保活核心**：`automation/login.py` 一行不动。digest 拉取失败只记日志，签到照常（错误隔离）。

## 配置模型

两层，职责分开：

| 层级 | 变量 | 默认 | 作用 |
|---|---|---|---|
| **账户级开关** | `MTEAM_DIGEST_ENABLED_<n>` | `false` | 决定哪些账户的签到通知里带 digest |
| **全局参数** | `MTEAM_DIGEST_MIN_IMDB` | `8.0` | IMDB 评分下限 |
| | `MTEAM_DIGEST_TYPES` | `movie,tvshow` | 资源类型（search mode，逗号分隔） |
| | `MTEAM_DIGEST_HOURS` | `24` | 发布时间窗口（小时） |
| | `MTEAM_DIGEST_LIMIT` | `10` | 最多列出条数 |

- 开关按账户（"要不要在我这条通知里看到"是个人偏好）；参数全局（内容全站一样）。
- 默认全部账户**关闭**，不影响现有用户。
- `Account` 新增 `digest_enabled: bool` 属性（解析 `MTEAM_DIGEST_ENABLED_<n>`）。
- `Settings` 新增 `digest_min_imdb` / `digest_types: list[str]` / `digest_hours` / `digest_limit`。

### `.env.template` 配置示例（含类型备注）

```ini
# ── 高分新片摘要（拼进签到通知；按账户开关）──────────────────
# 账户级开关（默认 false）：
# MTEAM_DIGEST_ENABLED_1=true

# 全局参数：
# IMDB 评分下限
MTEAM_DIGEST_MIN_IMDB=8.0
# 资源类型（search mode，逗号分隔）
# 可选: movie(电影) / tvshow(电视剧) / music(音乐) / adult(成人)
#        / waterfall(瀑布流) / rss / rankings(排行) / all(全部) / normal(综合)
# 注意: music/adult 等非影视类型没有 IMDB 评分，会被评分过滤滤光，不适合本功能。
# 默认只看影视:
MTEAM_DIGEST_TYPES=movie,tvshow
# 发布时间窗口（小时）
MTEAM_DIGEST_HOURS=24
# 最多列出条数
MTEAM_DIGEST_LIMIT=10
```

## 架构与数据流

```
新增 api/digest.py（纯 HTTP，不依赖浏览器）：
  fetch_high_score_digest(api_key, *, base_url, min_imdb, types, hours, limit) -> list[dict]
    └ for mode in types: search_torrents(api_key, "", mode=mode, page_size=100)
    └ 本地过滤：imdbRating ≥ min_imdb  且  createdDate 在 hours 窗口内
    └ 按 imdb 降序，截断到 limit
  format_digest(rows) -> str    # 生成通知文本片段（精简、邮件安全）

runner.py：
  run_all_accounts():
    ├ 若【任一账户】digest_enabled → 选第一个 can_query 账户拉一次 → digest_text
    │   （无账户开启 → 完全不拉，零开销；拉取失败 → 只记日志，digest_text=""）
    └ 循环账户：run_one_account_tick(acct, ..., digest_text)
  run_one_account_tick(..., digest_text=""):
    └ 签到成功后：
         通知正文 = profile_text + (acct.digest_enabled and digest_text
                                     ? "\n\n" + digest_text : "")
```

## 过滤实现细节（`api/digest.py`）

```python
async def fetch_high_score_digest(api_key, *, base_url, min_imdb, types, hours, limit):
    rows = []
    for mode in types:
        data = await search_torrents(api_key, "", mode=mode,
                                     base_url=base_url, page_size=100)
        for t in as_list(data):
            imdb = _parse_float(t.get("imdbRating"))   # "" / None → 跳过
            if imdb is None or imdb < min_imdb:
                continue
            age = _age_hours(t.get("createdDate"))
            if age is not None and age > hours:        # 解析失败 → 保留（宁多勿漏）
                continue
            rows.append(_shape(t, imdb))
    rows.sort(key=lambda r: r["imdb"], reverse=True)
    return rows[:limit]
```

判断点（按健壮性处理，不臆测）：
- **空关键词搜索**：`keyword=""` + `mode=movie` 取该类目最新。若 M-Team 不接受空关键词，回退用宽泛词或 `mode=normal` + 类目过滤——**实现时实测确认**（沿用项目 probe-verified 纪律）。
- **`imdbRating` 为空/非数字**：`_parse_float` 返回 None → 跳过（很多资源没评分，正常）。
- **`createdDate` 解析失败**：保守**保留**（宁可多发不漏）。
- **去重**：同片多版本（4K/1080p）会多条；v1 **不去重**，如实列出（简单优先，日后可加）。

`_shape(t, imdb)` 产出字段：`id` / `title`(smallDescr or name) / `type`(mode 中文名) / `imdb` / `douban` / `size` / `createdDate`。

## `mteam-cli digest` 命令

```
mteam-cli digest [--account NAME] [--min-imdb 8.0] [--types movie,tvshow]
                 [--hours 24] [-n 10] [-f table|json|yaml|csv|md|plain] [--raw]
```

- 复用数据命令的 `_query` 脚手架（`run`/`fetch`/`require_query`/`resolve_account_or_exit`）；`--account` 默认第一个有 api_key 的账户。
- 命令行参数**覆盖**全局 env 默认值，方便临时调阈值看效果。
- 输出走现有 `emit_rows`（table/json/...），`--raw` 给完整 JSON。
- 不依赖签到，随时手动跑。

字段列：`#` / `ID` / `标题` / `类型` / `IMDB` / `豆瓣` / `大小` / `发布时间`。

## 通知格式（`format_digest`）

签到通知尾部拼接，精简、邮件安全（参考 QQ 550 教训，不堆砌敏感字段）：

```
📽 今日高分新片 (IMDB≥8.0)
• [9.3] 某电影名 (电影)
• [8.5] 某剧名 (电视剧)
```

空结果（当天无高分新片）：**整段省略**，签到通知尾部不加任何 digest 内容（保持通知简洁，无新片时不打扰）。`format_digest([])` 返回空字符串，拼接处对空字符串短路。

## 受影响文件

| 文件 | 改动 |
|---|---|
| `api/digest.py` | **新增**：`fetch_high_score_digest` + `format_digest` + 解析辅助 |
| `api/__init__.py` | 导出新函数 |
| `core/config.py` | `Account.digest_enabled` + `Settings.digest_*` + 解析 |
| `automation/runner.py` | `run_all_accounts` 拉一次 + `run_one_account_tick` 拼接 |
| `cli/commands/digest.py` | **新增**：`digest` 命令 |
| `cli/main.py` | 注册 `digest` 命令 |
| `.env.template` | 新增配置段（含类型备注） |
| `docker-compose.yaml` / `k8s statefulset.yaml` | 新增 env 示例 |
| `CLAUDE.md` / `README.md` | 文档 |

## 测试

- `_parse_float` / `_age_hours`：空值、非数字、各种日期格式、解析失败保留。
- `fetch_high_score_digest`：mock `search_torrents` 返回混合数据，验证阈值/时间窗/排序/截断/不去重。
- `format_digest`：空结果、单条、多条。
- 配置解析：`MTEAM_DIGEST_ENABLED_<n>` 默认 false、各全局参数默认值与覆盖。
- 端到端（用户真实环境）：`mteam-cli digest` 对真实 api_key 返回合理结果（probe 空关键词搜索行为）。

## 非目标（YAGNI）

- 不做去重、不做 IMDB 之外的多维排序、不做历史去重（"昨天发过的今天不再发"）。
- 不引入 RSS。
- digest 不单独成调度任务，仅随签到。
