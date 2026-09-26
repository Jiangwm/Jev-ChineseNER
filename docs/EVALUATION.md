# 评测与中文验证

**当前真实 Jev 中文验证状态为 `not_run`。** 真实调用和独立中文实验尚未执行。
本地测试证明程序约束、SDK 合约与回退行为，不能证明模型准确性，也不预设 Jev 优于本地中文分词。

以下路线与指标对应 [设计第七节](DESIGN.md)。提供可运行工程骨架，正式中文验证属于 B 阶段。

## 当前路线

| route | 实现 | 用途 |
|---|---|---|
| `jieba` | 原生 jieba 分词，HMM=False | 最低本地基线；没有类型/内部成分，相关指标返回 null |
| `jieba_lexicon` | 独立 jieba tokenizer 注入同版词库和别名，精确 span 匹配附加类型/成分 | 设计要求的 jieba+词库；词库外单位没有类型/角色预测 |
| `local_graph` | 本地分词候选+同版词库+规则；边界 p=0.5，无模型 | 设计要求的本地分词+词库组合基线，隔离模型收益 |
| `boundary_jev` | 每个间隙一个 Noul，以 0.5 工程初值切分 | 最小原型及中文边界能力探针；没有类型层指标 |
| `hybrid_jev` | 两轮判定 + 词图 + 双层输出 | 完整待验证路线 |
| `selective_jev` | 核验快速通道 + 仅未命中时 Jev | 设计要求的快路径+选择性 Jev，单独报告 fast_path_rate |
| `mock` | 合成 Noul/Choice + 相同解码 | 工程测试，不可记作 Jev 成绩 |

除明确测量快速通道的 `selective_jev` 外，所有词图路线在评测时禁用快速输入记忆。
演示标注仍与词库重叠，故成绩不能代表泛化。选择性路线仅用于测量调度，不得将其与强制
推理路线的模型质量直接混算。真实 Jev 路线遇需推理但缺 key、上游失败或降级即中止评测，
不生成伪成功报告；全部为核验输入时允许零调用，并在 fast_path_rate 明示。

```bash
uv run jev-evaluate --gold fixtures/gold.jsonl --route local_graph --output reports/local.json
uv run jev-evaluate --gold fixtures/gold.jsonl --route hybrid_jev --output reports/jev.json
```

## 已计算指标

- 地理单元 boundary micro P/R/F1、单元 span micro P/R/F1、整条 exact match。
- 词图解码前候选召回：完整 gold span 是否在图中，以及 span+本地初始类型是否存在；
  `gold_path_reachable_rate` 要求一条样本所有 gold 单元都在图中（可首尾连成完整路径）；
  对纯 jieba / 全间隙路线为 null。它区分候选召回与最终解码错误，不包含模型补充的类型。
- 单元 span+类型 P/R/F1；成分 span+角色+父 span 联合 P/R/F1，不把两种粒度合并算分。
- `components.span_parent`：忽略角色的父内跨度 F1；`role_macro_f1`：按预测或 gold
  中出现的角色等权平均，命中须父跨度+成分跨度+角色一致；同时输出 `per_role`。
- 标注 `oov=true` 的完整单元召回率。
- 真实单元边界 Noul 的 Brier、10 等宽 bin ECE、`reliability_curve`（每 bin 样本数、
  平均预测概率、实际边界频率），可直接绘制校准曲线；没有真实概率时为 null/空曲线。
- 端到端 p50/p95 延迟、成功模型调用数、input_tokens、降级比例及逐样例结果。
- `cost_usd=null`：不臆造价格或将工程测试当实际账单。

当前小样例计时包含冷启动，不能当生产延迟。正式实验要分别报告冷/热启动、并发数、重试和
实际计费成本；失败/被取消的请求可能已计费。成本字段需从计费数据补齐。

## B：尚待执行的实验

1. 完成目标 2k–5k 的独立标注与严格 train/dev/test 切分。
2. 单独验证 Jev 中文：汉字、方位与自治名称、机构/POI、未登录词；分析原文、问题、候选、
   答案和解码错误分别来自召回、判定、组合还是上游失败。
3. 对照中文专用分词/NER 模型、领域词库基线、boundary Jev、完整词图；新增路线采用同一
   金标准与输出适配层，不改测试集迎合模型。
4. 做词库/规则/地域上下文/第二轮/边界概率的消融，按地域、词长、OOV 等切片。
5. 仅在 dev 调边权、接受/歧义阈值及校准器；独立 test 报统计区间、人工复核率、覆盖率与错误率。
6. 根据效果、延迟、成本决定是否保留 Jev、仅疑难路由或替换本地模型，不把模型品牌当验收结论。

设计没有给出数值上线门槛；当前不虚构通过阈值，需在 B 实验中按任务风险核定。报告保留 `pending_metrics`
供后续人工歧义复核、分层和计费对接。

正式数据须提供 `place_groups`（地名 canonical/别名/名称族共享组），同组不能跨 train/dev/test。
先验证全文件以捕获跨集泄漏，再通过 `--split test` 选择评测部分。demo 可不提供分组；现有
20 条样例已带演示分组，不因此变为独立测试集。未指定 split 时报告 all，不能将混合成绩称为测试成绩。

```bash
uv run jev-evaluate --gold fixtures/gold.jsonl --split demo --route local_graph --output reports/local.json
```
