# 已读取资料与集成核对

读取日期：2026-09-20。使用技能：
`/home/box/.codex/skills/typesafe-ai/SKILL.md`（工作环境的 `~/.codex/skills/typesafe-ai`）。
网页浏览工具返回不可访问后，通过 HTTPS 直接获取下列官方 Markdown。

| 来源 | 本项目采用的内容 |
|---|---|
| [官方文档索引](https://docs.typesafe.ai/llms.txt) | 定位 SDK、原语、cookbook、模型说明 |
| [Python SDK](https://docs.typesafe.ai/sdk/python.md) | AsyncTypeSafeClient、typed questions、response.answers |
| [Noul](https://docs.typesafe.ai/primitives/noul.md) | 边界使用 yes 概率，没有另一个 confidence |
| [Choice](https://docs.typesafe.ai/primitives/choice.md) | 封闭选项与分布，unknown / not_entity 退出项 |
| [预解析抽取 cookbook](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook.md) | 代码找候选，模型判定，再由代码复制原文 |
| [异步客户端](https://docs.typesafe.ai/sdk/python/api/clients/async.md) | 批量问题、模型覆盖、超时 |
| [响应](https://docs.typesafe.ai/sdk/python/api/types/responses.md) | 原始回答、usage 与实际模型版本 |
| [重试](https://docs.typesafe.ai/sdk/python/api/retries.md) | 重试预算与失败语义 |
| [模型说明](https://docs.typesafe.ai/models.md) | 固定版本、中文需专门测试 |
| [Jev 1.13 已知局限](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md) | 计数和结构不变量由代码处理 |

SDK 安装后额外检查真实签名，并用其 HTTP transport 替身跑合约测试。
本项目固定 `typesafe-sdk==0.5.7`；其配置使用 `retry=RetryPolicy(max_retries=1)`。
模型每次请求显式传 `jev-1.13.0`，返回版本再核对。文档示例中使用滚动别名的部分没有照搬。
外部 cookbook 的阈值和效果数字不作为本项目中文阈值或实验数据。


## 2026-09-21 演示资产扩展

仅使用公开地名和项目编写的演示标注；未外部采集，未写入私人真实住址。
词库从 24 增至 **36 条**（+12），覆盖省/自治区、市、区、道路及机构；新增条目
`version=demo-2026.09.21`，逐条记录来源、别名、父关系与成分。父关系只表示演示归属，
不用于实体链接；机构按城市归属，不保证指向单一校址。`valid_from/to=null` 表示历史有效期未标注。
包内既有词库版本标签保持不变，内容以响应中的 `lexicon_fingerprint` 区分。

金标准演示样例从 12 增至 **20 条**（+8），全部 `split=demo` 且有 `place_groups`；
厦门简称与厦门市共用 `demo:xm`。新增标注是按既有规范编写的预备资产，未经双人独立
标注和裁决。**演示重叠、非独立泛化**；2k–5k 正式标注、真实 Jev 中文验证仍属 B 后续。
反例从 10 增至 **15 条**（+5）；新增 `assertions` 字段供 `tests/test_demo_assets.py`
在 mock/local 两条路径禁用快路径执行，`expect` 保留人可读的错误切分/类型说明。

核验快速输入仍为 **7 条**，新增 0 条；检查原有完整单元和成分仍有效后，仅更新它们绑定的指纹：

- 扩展前：`5415dac1d35361a98845074a09610d1527253c59398c903b5ccf05a5e33683d5`
- 扩展后：`1f335ca940b8735c83a7e52d933ad01d51237c45c4e998d1db74f0cf49c6943b`

四条离线报告已用 20 条演示样例重新生成；命令和结果见 [VALIDATION.md](VALIDATION.md)。
本次未调用真实 Jev，`chinese_validation=not_run`。
