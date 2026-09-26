# 标注规范 annotation-0.1.0

当前只提供 **20 条项目编写的演示样例**，见 `fixtures/gold.jsonl`。它们不是随机抽样、不具备独立
测试集资格，其中多条与词库及回归用例重叠。目标 **2k–5k** 条，目前没有声称已经完成该规模。

## 双层定义

地理单元是输入地址中的完整命名单元。`江苏省/南京市/栖霞区/仙林大道` 属于单元层；
`仙林/大道` 属于该道路父节点的内部成分。不要将两层摊平成同一个分词串。

单元类型包括省、城市、区县、乡镇/街道、村、道路、桥梁、水体、山体、POI、机构、门牌、
separator、unknown、not_entity。成分角色包括 proper_name、generic、qualifier、number、
unknown、not_entity。内部成分不再承载城市实体标签。

| 例子 | 单元划分 | 内部成分 / 判定依据 |
|---|---|---|
| 南京市长江大桥 | 南京市 / 长江大桥 | 南京/市；长江/大桥 |
| 上海市南京东路 | 上海市 / 南京东路 | 南京是道路专名成分；东是限定；路是通名 |
| 东莞市 | 东莞市 | 东莞/市，不拆“东” |
| 内蒙古自治区 | 内蒙古自治区 | 内蒙古/自治区，不拆“内” |
| 广西壮族自治区 | 广西壮族自治区 | 广西/壮族/自治区 |
| 南京大学 | 南京大学 | 默认 organization；词名本身不唯一指向物理校区 |
| 南京大学仙林校区 | 南京大学仙林校区 | 具体校区可标 poi；不意味着进行了实体链接 |

`南京长江大桥` 可有整座桥名与上下文“南京/长江大桥”的方案竞争；正式标注需要上下文和
双人复核，不能从候选最优分数倒推出金标准。本版将其放在歧义反例而非单一真值金标准。

## JSONL 格式

每行一个 `GoldDocument`，JSON Schema 在 `gold.schema.json`，Python 验证在 `gold.py`。
父子关系通过 `units[].components` 的嵌套表达；所有 span 均为原文绝对 codepoint 偏移。

```json
{"id":"road-example","text":"南京东路","input_kind":"place_name","annotation_version":"annotation-0.1.0","split":"demo","units":[{"span":[0,4],"entity_type":"road","oov":false,"components":[{"span":[0,2],"role":"proper_name"},{"span":[2,3],"role":"qualifier"},{"span":[3,4],"role":"generic"}]}],"notes":"南京为道路内部专名"}
```

原文保留空白、标点、全角数字与补充平面字符；不靠规范化字符串计算偏移。
`oov` 指在冻结的评测词库里未收录该完整 surface，须由标注工具针对词库版本复核。
未知文本也必须覆盖；无法确定用 unknown，不造实体 ID。机构不等于地理实体，仍可作为完整
非地理名称单元保留，地理任务下游应按 entity_type 筛选。

## 领域词库

`data/lexicon.json` 共 36 条，schema 在 `lexicon.schema.json`：
`entity_id/canonical_name/aliases/entity_type/parent_relations/verified_components/valid_from/valid_to/source/version`。
ID 使用 `demo:` 命名空间，父关系只是人工演示关系，不能当权威行政或地理编码数据。
`valid_from/to=null` 表示未标注历史有效期，非证明永久有效；匹配时在代码中按 UTC 当日过滤
已标注的有效期。成分 span 相对于 canonical_name；别名不盲套规范名偏移。

词条及成分由项目人工构造，未抓取或宣称拥有外部大型词库；后续引入外部资产应记录许可、
来源日期和版本。`rules.json` 带机械误拆反例；`fixtures/counterexamples.json` 保存任务层反例。

## 扩展标注计划（B）

按地域、行政级别、道路桥梁、少数民族自治名称、方向歧义、门牌、简称/别名、机构/场所、
未登录词和混合字符分层采样。双人独立标注后裁决，记录争议和可接受备选。
按名称族、地域和来源隔离 train/dev/test，禁止同名别名跨集合泄漏；先冻结标注规范和词库。
校准参数只在训练/开发集拟合，在独立测试集报告 ECE、Brier 与任务指标。

`place_groups` 记录样本涉及的规范地名/名称族 ID（数组）。正式 train/dev/test 样本必填且非空；
同一名称、别名、同族变体须用同一组。多个地名共现可能连接多个组，应整体放入同一集合。
`validate_dataset` 在评测前拒绝跨集共享组；分组本身仍需要人工核验，不能单凭表面字符串
证明无泄漏。demo 分组仅演示格式。`--split` 过滤发生在全文件分组验证之后。
