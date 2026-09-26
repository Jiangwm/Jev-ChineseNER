# 设计差距审计

审计日期：2026-09-20。依据 `docs/DESIGN.md`、`/workspace/jev-chinese-ner-design.md`
及本次用户的实现/验收要求；两份设计通过 `cmp`，字节一致。已阅读 `DESIGN_GAPS.md`：
当前设计是完整结构落地稿，无法恢复更早对话的逐字修辞，不据此臆造要求或阻塞已授权实现。
沿用已有 Python 包、候选图、SDK 适配和 API 结构，没有重建项目。

状态定义：**已实现**有代码/资产/可运行检查；**部分**为工程入口已有、真实数据/实验仍待 B/D；
**缺失（B/D 后续）**只用于明确超出本轮 A/C 范围的工作。A/C 核心未解决缺失为 **0**。
真实 Jev 中文效果未验证，工程验收不能替代 B 阶段实验。

## 一至九逐项对照

| 设计条款 | 初审 | 补齐后 | 证据 / 限制 |
|---|---|---|---|
| 一：单元与成分两层、父子关系 | 已实现 | 已实现 | `models.Unit.components` / `Component.parent_id`，道路内南京仅为 proper_name |
| 一：单地名/短地址范围 | 已实现 | 已实现 | `SegmentRequest` 1–128 codepoint；篇章 text 预留枚举并明确 422 |
| 二：原文、地域上下文、无损预处理 | 已实现 | 已实现 | 不改写输入的身份映射；NFKC 仅显示；Unicode 和随机字符回归 |
| 二：本地已验证快路径 | 部分 | 已实现 | 原有 7 条精确输入；新增词库 SHA-256、input_kind 范围、完整成分和有效期检查；地域上下文仍绕过快路径 |
| 二：词库只提供证据，不强制语义 | 部分 | 已实现 | 非快速输入的词库候选也进入类型 Choice；可返回 not_entity；预算未复核的选中类型触发 ambiguous |
| 三：全间隙 Noul 最小原型 | 已实现 | 已实现 | `boundary_questions`、评测 `boundary_jev`；0.5 阈值只用于对照原型 |
| 三：词库/Trie、jieba、规则、未登录子串、单字 → DAG | 已实现 | 已实现 | `lexicon`、`candidates`；代码保证边界、连通和连续原文；规则资产缓存避免内部循环反复读文件 |
| 三：边界似然、词典/结构软分和 k-best DP | 已实现 | 已实现 | `decoder.decode`；无省市区道路硬语法；反序地址测试；路径分仅是排序能量 |
| 三：覆盖、不重叠、不丢字、父内成分 | 部分 | 已实现 | DAG + `validate_partition`；补充 ID 唯一、越界及可选但非空成分的完整覆盖检查 |
| 三：中文域边界校准和权重训练 | 部分 | 部分（B 后续） | 当前原始 Noul 经恒等映射与数值裁剪评分；`boundary_calibration=identity-not-fitted-v1`，无拟合数据，不能宣称已校准 |
| 四：Noul CUT；Choice 类型、角色、方案 | 部分 | 已实现 | `questions`/`components`；显式 CUT 和 span 标记，题干不依赖 ID；成分题不再沿用“单元内部不拆”规则；包含 unknown/not_entity；词库重新分类后不复用不适用成分 |
| 四：独立问题并行、必要时第二轮 | 已实现 | 已实现 | `providers` 有界并行与 TaskGroup 取消；解码后编译父内问题；SDK transport 合约测试 |
| 四：固定 jev-1.13.0、真实 SDK | 已实现 | 已实现 | SDK 0.5.7；请求和响应版本校验；新增配置赋值校验与 Choice argmax 一致性检查 |
| 五：POST、CLI、半开 codepoint 偏移 | 已实现 | 已实现 | `api`/`cli`；CLI dry-run 无网络；HTTP、全角数字、emoji 回归 |
| 五：ok/ambiguous/degraded、原始概率与接受分分离 | 已实现 | 已实现 | 真模型与 mock 分字段；接受分 null/not_fitted；错误返回本地完整结构 |
| 五：版本、证据、独立规范化、关闭链接 | 已实现 | 已实现 | 增加词库指纹、边界映射版本；entity_linking 仅 false，linked_entity_id=null |
| 六：完整词库 schema、verified_components、Trie | 已实现 | 已实现 | 36 个演示词条、别名、父关系、有效期、来源；`lexicon.schema.json` 与 Pydantic |
| 六：六组构词反例 | 已实现 | 已实现 | 南京市长江大桥、上海市南京东路、东莞市、内蒙古、广西、南京大学；共 15 条反例；新增北京路、东南大学、宁夏、厦门大学、市场的 mock/local 禁用快路径断言 |
| 六：金标准格式、少量样例、分组隔离 | 部分 | 已实现 | 20 条 demo；新增 place_groups，正式 train/dev/test 必须提供分组，评测先检查跨集泄漏；JSON Schema 同步 |
| 六：2k–5k 独立标注 | 缺失 | 缺失（B 后续） | 需采样、人工双标和裁决；本轮仅要求少量样例，不生成伪造正式数据 |
| 七：设计五种对照路线 | 已实现 | 已实现 | jieba_lexicon/local_graph/boundary_jev/hybrid_jev/selective_jev；另有原生 jieba/mock |
| 七：候选召回、路径可达、单元 F1/整串正确 | 部分 | 已实现 | 新增 gold_path_reachable_rate；候选类型召回为 Jev 前本地类型，不混入模型贡献 |
| 七：成分跨度、角色 Macro-F1、OOV、校准、延迟/成本 | 部分 | 已实现（工程入口） | 新增 span_parent、per_role、role_macro_f1；Brier/ECE/曲线、OOV、p50/p95、实际成功 input_tokens；账单成本 null |
| 七：真实中文实验、独立基线优劣和统计结论 | 缺失 | 缺失（B 后续） | 无真实远端实验和独立测试数据；真实路线失败中止，绝不冒充 Jev 成绩 |
| 八：三级路由、请求规模/并行/时限、敏感信息 | 已实现 | 已实现 | 默认 mock；核验快路径/模型/降级；上游异常脱敏；不写请求原文日志或凭据 |
| 八：生产缓存、连接池、预算、限流、监控 | 缺失 | 部分（D 骨架已实现） | 默认关闭的纯内存 LRU/TTL；键含完整请求/Settings/版本/资产指纹；命中来源和计数；进程内滑动窗口/请求预算。连接池、生产鉴权、熔断、实际成本预算和生产观测仍后续 |
| 八：私人地址生产治理 | 部分 | 部分（D 后续） | 演示/金标准仅公开地名或合成样例；用户显式选择 jev 时原文发送 TypeSafe；鉴权、脱敏策略、数据保留需部署方落地 |
| 九：A 定义和 C 可运行系统 | 部分 | 已实现 | 审计新增、上述实现补齐、pytest/安装/demo/HTTP 验证；保持现有模块边界 |
| 九：B 效果门槛与 D 生产优化 | 部分 | 部分（B/D 后续） | 不因 C 工程通过而声称可生产；下一步按真实中文效果/成本选择保留、选择性调用或替换判定器 |

## 本次补齐与验证定位

2026-09-21 D 增量：**缓存骨架已实现（默认关）**，`cache.py` / `service.py` 缓存最终结果，
`diagnostics.cache_hit` 标记来源；缓存与准入计数可读，无地址日志/磁盘缓存。
`config.py` 提供显式开关和容量/TTL/窗口/请求预算，`api.py` 将超限映射为固定错误码 HTTP 429。
`tests/test_cache.py` 覆盖跳过 Judge、版本/资产/请求/配置失效、TTL/LRU、深拷贝及本地超限。
连接池/生产鉴权/熔断仍后续；预算按请求数，不宣称实际费用约束或 B 真实中文实验完成。
本轮新增 43 项测试，全量 `112 passed, 1 warning in 1.98s`；改动文件 Ruff 检查及格式检查通过。
warning 来自依赖中的 Starlette/AnyIO 弃用提示。

- `questions.py`：词库类型可复核，去重问题，显式候选标记。
- `service.py` / `verified_inputs.json`：快路径绑定资产及范围、模型否定后的成分处理、未复核标志、最终硬约束。
- `lexicon.py` / `config.py` / `providers.py`：资产指纹、模型赋值锁定、非法 Choice 拒绝。
- `evaluation.py` / `gold.py` / `gold.schema.json`：指标补齐、分组泄漏检查、`--split` 选择。
- `tests/`：A/C 补齐时由 35 项扩展为 48 项；2026-09-21 演示资产扩展后 69 项通过，覆盖上述行为及全部指定反例的非快路径运行；最终结果见 [VALIDATION.md](VALIDATION.md)。

未改 `~/.codex/config.toml`，未使用 Shepherd，未写入或提交真实密钥。工作目录没有 `.git`，
因此此次交付为工作区文件更新，不包含 commit/PR。已读官方文档和 SDK 对照见 [SOURCES.md](SOURCES.md)。
