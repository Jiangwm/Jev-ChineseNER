# 配置

默认配置见 `src/jev_chinesener/config.py`，环境示例见根目录 `.env.example`。
`.env` 不会自动加载。API 可通过 shell 环境变量配置；CLI 的 `--backend` 覆盖环境。

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `TYPESAFE_API_KEY` | 空 | 仅 Jev 后端需要；不打印或落盘 |
| `JEV_BACKEND` | `mock` | `mock` / `local` / `jev`，有密钥也不自动联网 |
| `JEV_MODEL` | `jev-1.13.0` | 当前仅接受这一固定版本，拒绝滚动别名 |
| `JEV_TIMEOUT_SECONDS` | 20 | 每轮总时限，含所有分块、排队和重试 |
| `JEV_BATCH_SIZE` | 24 | 单请求独立问题数，上限 64 |
| `JEV_CONCURRENCY` | 4 | 同一适配器最多同时进行的请求 |
| `JEV_CACHE_ENABLED` | `0` | 显式设为 `1` 开启进程内响应缓存 |
| `JEV_CACHE_MAX_ENTRIES` | 256 | 每个 Segmenter 的 LRU 最大条目数，至少 1 |
| `JEV_CACHE_TTL_SECONDS` | 300 | 写入起算的有效秒数，须为有限正数；命中不续期 |
| `JEV_RATE_LIMIT_REQUESTS` | 0 | 滑动窗口最多准入请求数；0 关闭 |
| `JEV_RATE_LIMIT_WINDOW_SECONDS` | 60 | 滑动窗口秒数，须为有限正数 |
| `JEV_REQUEST_BUDGET` | 0 | 进程累计准入请求预算；0 关闭，重启清零 |

Python `Settings` 还支持 `fast_path`、`max_candidate_length`（默认 16）、
`ambiguity_margin`（默认 0.8）。这些权重和阈值是未调优工程初值，不是中文验证结论。
API 输入上限为 128 个 Unicode codepoint，地域上下文上限 256，`top_k` 上限 5。
类型问题只询问前 48 个疑难候选；未询问候选保留本地证据/unknown。
内部角色每个父单元最多询问 48 个候选。第二轮成分与局部方案问题可共批，彼此独立。

**D 缓存骨架已实现（默认关）**。Python 对应字段为 `cache_enabled`、`cache_max_entries`、
`cache_ttl_seconds`、`rate_limit_requests`、`rate_limit_window_seconds`、`request_budget`。
缓存键包含完整请求、全部 Settings、版本与已加载资产指纹，纯内存且不记录原文日志。
启用后用 `diagnostics.cache_hit` 区分来源；`engine.cache.stats()` / `engine.limits.stats()`
可读取观测计数。限流/预算在缓存查询前执行，缓存命中也消耗一次准入，拒绝不消耗预算；
HTTP 429 错误码为 `rate_limit_exceeded` / `request_budget_exhausted`。
默认同进程共享准入计数，部署使用统一窗口配置；不跨 worker 协调，不是 token 或金额预算。
连接池、生产鉴权、熔断及生产观测仍待后续，B 真实中文实验未完成。
