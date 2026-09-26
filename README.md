# Jev-ChineseNER

Jev 驱动的中文地名多粒度分词器。程序构建字符边界与候选词图，Jev 对边界、类型和角色作独立判定，确定性代码解码并保证原文完整覆盖。仓库名保持 `Jev-ChineseNER`。

设计依据为 [docs/DESIGN.md](docs/DESIGN.md) 与内容一致的
`/workspace/jev-chinese-ner-design.md`（结构完整落地稿）；原对话逐字文本的限制见
[DESIGN_GAPS](docs/DESIGN_GAPS.md)。设计一至九节的初审、补齐和 B/D 后续事项见
[差距审计](docs/GAP_AUDIT.md)，交付范围见 [验收对照](docs/ACCEPTANCE.md)。

阶段一支持单地名、短地址。双粒度保持父子结构：

```text
江苏省 / 南京市 / 栖霞区 / 仙林大道     ← 地理单元
                              ├ 仙林  proper_name
                              └ 大道  generic

上海市 / 南京东路
         ├ 南京  proper_name              ← 不是独立 city 实体
         ├ 东    qualifier
         └ 路    generic
```

Jev 中文能力尚未运行真实验证，不预设优于 jieba 或其他本地中文方案。
默认 `mock` 无网络；只有精确命中本地人工核验输入、输入范围和词库指纹一致才快速返回 `ok`，其余 mock 输出为 `degraded`。
真实后端固定 `jev-1.13.0`。没有训练过的接受分校准器，因此接受分返回 `null`。

## 安装与运行

Python 3.11+；已用 Python 3.12 验证。推荐 `uv.lock` 复现依赖。

```bash
cd /workspace/AGIworkspace/Jev-ChineseNER
uv sync --extra dev --frozen

# 或用 pip 安装可发布包
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# CLI 和离线 demo
uv run jev-chinesener '上海市南京东路'
uv run jev-chinesener '星海路１３８号' --backend mock
uv run jev-chinesener '南京市长江大桥' --dry-run
uv run python scripts/demo.py

# API，OpenAPI 交互文档：http://127.0.0.1:8000/docs
uv run uvicorn jev_chinesener.api:app --host 127.0.0.1 --port 8000
```

```bash
curl -s http://127.0.0.1:8000/v1/toponyms/segment \
  -H 'Content-Type: application/json' \
  -d '{"text":"上海市南京东路","input_kind":"address","granularity":"both","return_components":true,"top_k":3}'
```

显式选择 jev 会把原文及地域上下文发送到 TypeSafe；demo 仅用公开地名和合成输入。
真实 Jev 需在本机环境设置 `TYPESAFE_API_KEY`，然后显式选择后端：

```bash
export JEV_BACKEND=jev
export JEV_MODEL=jev-1.13.0
uv run jev-chinesener '星海路１３８号' --backend jev --region-context '江苏省南京市'
```

缺 key、超时、错误模型版本或非法模型响应均返回带原因的 `degraded` 本地结果。
CLI `--dry-run` 只输出第一轮问题与候选，永不发请求；`--no-fast-path` 可检查完整推理流程。
密钥通过环境提供，`.env` 已忽略，代码不自动读取或输出密钥。

## API 契约

`POST /v1/toponyms/segment`：

| 字段 | 取值 / 语义 |
|---|---|
| `text` | 1–128 个 Unicode codepoint 的原文 |
| `input_kind` | `place_name` / `address`；`text` 在 schema 中保留，阶段一明确返回 422 `unsupported_scope` |
| `granularity` | `geographic_unit` / `name_component` / `both`，默认 `both` |
| `return_components` | 默认 true；`name_component` 和 `both` 强制保留成分；只要单元用 `geographic_unit` + false |
| `top_k` | 1–5，**包含主结果**；最多返回 `top_k - 1` 个替代方案 |
| `region_context` | 可选地域字符串，仅作语义上下文，不硬性约束行政层级 |
| `entity_linking` | 默认 false，本阶段只允许 false |

主结果始终是 `units`，细粒度位于各单元的 `components`，不会将两层混成一串。
所有 `text == 原文[span.start:span.end]`，偏移是 Unicode codepoint、左闭右开。
空格、标点和未知字符也有覆盖。`normalized_name` 是独立展示字段；别名可能显示词库规范名，
不改变原文偏移、不自动简繁转换、不证明实体链接。`lexicon_entity_id` 仅为词库证据，
`linked_entity_id` 始终为 null。

`status`：`ok`（本地核验或模型路径未触发当前歧义策略）、`ambiguous`（保留竞争/未知）、
`degraded`（mock、本地回退或外部判定失败，优先级最高）。`ok` 不是已校准质量保证。
`raw_model_probabilities` 只放真实模型响应；`mock_judgments` 单独放合成测试输出。
`calibrated_acceptance_score=null`、`calibration_status=not_fitted`；路径 `score` 是排序能量。
边界评分暂用恒等映射并显式标为 `identity-not-fitted-v1`，不声称做过中文校准。
响应包含词库内容指纹、词库版本、规则、标注规范、提示、模型、校准及规范化版本和逐单元证据。

**D 缓存骨架已实现（默认关）**：显式设置 `JEV_CACHE_ENABLED=1` 后，同一服务实例可复用
完整最终结果，命中时 `diagnostics.cache_hit=true` 且跳过 Judge。纯内存 LRU/TTL 的键覆盖
原文、粒度、地域上下文、top_k、全部 Settings、模型/校准版本和资产指纹；版本或已加载资产
变更自动 miss，不写地址日志或磁盘缓存。`engine.cache.stats()` 可读命中/未命中计数。
可选进程内滑动窗口限流与请求总预算超限返回 HTTP 429（固定本地错误码），命中也计入准入数；
配置和默认值见 [config/README.md](config/README.md)。连接池、生产鉴权、熔断仍待后续；
此骨架不代表 B 真实中文实验完成或系统可生产。

## 测试、评测与构建

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run jev-evaluate --route jieba --output reports/jieba.json
uv run jev-evaluate --route jieba_lexicon --output reports/jieba-lexicon.json
uv run jev-evaluate --route local_graph --output reports/local.json
uv run jev-evaluate --route mock --output reports/mock.json
uv build

# 下列是真实中文验证入口，需有效 key；失败会中止，不会冒充 Jev 成绩
uv run jev-evaluate --route boundary_jev --output reports/boundary-jev.json
uv run jev-evaluate --route hybrid_jev --output reports/hybrid-jev.json
uv run jev-evaluate --route selective_jev --output reports/selective-jev.json
```

演示资产：36 个词条、7 个精确核验快速输入、20 个金标准演示样例、15 条反例。
新增反例由 mock/local 禁用快路径自动断言；演示样例与词库重叠，属于「演示重叠、非独立泛化」。金标准规模目标为 **2k–5k**，
目前尚未建设完成。[标注说明](docs/ANNOTATION.md) 和 [评测方案](docs/EVALUATION.md) 说明数据隔离、
中文验证门槛、对照路线及指标；真实 Jev、统计比较、校准训练属于 B 实验阶段。

## 目录

```text
Jev-ChineseNER/
├── pyproject.toml, uv.lock, .env.example
├── README.md, ARCHITECTURE.md
├── config/README.md
├── docs/
│   ├── DESIGN.md, DESIGN_GAPS.md  # 结构完整设计与来源边界
│   ├── GAP_AUDIT.md              # 初审 / 补齐后 / B、D 后续
│   ├── ACCEPTANCE.md             # 设计一至九 / A、C 核心 / B、D 后续
│   ├── ANNOTATION.md, EVALUATION.md, SOURCES.md
│   └── lexicon.schema.json, gold.schema.json
├── src/jev_chinesener/
│   ├── models.py, config.py, lexicon.py, candidates.py
│   ├── questions.py, providers.py, decoder.py, components.py
│   ├── service.py, cache.py, api.py, cli.py, evaluation.py, gold.py
│   └── data/                     # lexicon / rules / verified_inputs
├── fixtures/gold.jsonl, counterexamples.json
├── scripts/demo.py
└── tests/                        # 回归、无损覆盖、真实 SDK 合约、评测失败语义
```

设计实现细节见 [ARCHITECTURE.md](ARCHITECTURE.md)。未修改 `~/.codex/config.toml`，未使用 Shepherd。
