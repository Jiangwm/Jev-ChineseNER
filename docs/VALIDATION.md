# 本地验证记录

## 2026-09-21 演示资产扩展验收

词库 36 条（+12），gold 20 条（+8），反例 15 条（+5），精确核验输入保持 7 条。
Pydantic 加载、与两份 JSON Schema 的一致性、双层原文覆盖、Trie 规范名/别名匹配、
父关系引用及全文件分组泄漏检查均通过。词库内容指纹已变化，原有核验输入绑定同步；
旧指纹拒绝测试通过。新增 5 条反例均在 mock/local 禁用快路径断言，8 条 gold 新样例
在 mock 禁用快路径核对单元类型、成分角色与绝对偏移；简称跨正式集合泄漏被拒绝。

`.venv/bin/pytest -q`：**69 passed, 1 warning**（原有 48 + 新增 21），exit 0。
警告仍为 Starlette 使用 AnyIO 弃用别名。新增测试文件 Ruff 检查与格式检查通过。

| route | 样例数 | 单元整串正确率 | 单元跨度 F1 | 成分角色 Macro-F1 | gold 路径可达率 |
|---|---:|---:|---:|---:|---:|
| jieba | 20 | 0.7000 | 0.6889 | 不适用 | 不适用 |
| jieba_lexicon | 20 | 0.9000 | 0.9000 | 0.7395 | 不适用 |
| local_graph | 20 | 1.0000 | 1.0000 | 0.7916 | 1.0000 |
| mock | 20 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

四条路线均禁用快路径，API 请求均为 0。报告已覆盖到 `reports/` 对应文件。
全部是**演示重叠、非独立泛化**的冒烟成绩；mock 使用合成判定，不代表 Jev 效果。
`chinese_validation=not_run`，2k–5k 正式标注和 B 真实实验仍未完成。

本次实际运行的评测命令（使用已有虚拟环境，不触发依赖联网）：

```bash
.venv/bin/jev-evaluate --gold fixtures/gold.jsonl --route mock --output reports/mock.json
.venv/bin/jev-evaluate --gold fixtures/gold.jsonl --route local_graph --output reports/local.json
.venv/bin/jev-evaluate --gold fixtures/gold.jsonl --route jieba_lexicon --output reports/jieba-lexicon.json
.venv/bin/jev-evaluate --gold fixtures/gold.jsonl --route jieba --output reports/jieba.json
```

本次仅修改数据资产、测试、文档和离线报告；包结构/API/模型配置保持不变。
未初始化 git、未修改 `~/.codex/config.toml`、未写入真实 API key、未外联或使用 Shepherd。

## 2026-09-20 历史 A/C 验证记录

以下数字为扩展前历史记录；其中 12 样例报告已被上方 20 样例报告替代，构建和安装记录
仅代表当日执行，本次没有重新构建分发包。

本轮验收：2026-09-20，Python 3.12，依赖来自 `uv.lock`。真实 SDK 使用本地 HTTP transport
替身验证；没有真实 Jev 推理请求，`chinese_validation=not_run`。

| 实际执行检查 | 实际结果 |
|---|---|
| `uv sync --extra dev --frozen` | 成功，31 个包检查通过 |
| `uv run pytest -q` | **48 passed**，1.57s；基线为 35 passed |
| `uv run ruff check src tests scripts` | All checks passed |
| `uv run ruff format --check src tests scripts` | 19 个文件格式通过 |
| `uv build` | sdist 与 wheel 构建成功 |
| 仓库外临时虚拟环境 `uv pip install <wheel>` | 安装成功；CLI `东莞市 --backend mock` 返回 ok，包内词库与核验资产可加载 |
| 实际 uvicorn + HTTP POST | 200，status=ok；上海市/南京东路，道路子成分南京/东/路；/health 正常；临时进程已关闭 |
| CLI `南京市长江大桥 --backend jev --dry-run`（删除 key 环境变量） | 合法 JSON，模型 jev-1.13.0，39 候选、36 个第一轮问题，其中 6 个 Noul；不调用推理 |
| CLI `星海路 --backend jev`（删除 key 环境变量） | 完整本地结果，status=degraded，原因 missing_api_key |
| `uv run python scripts/demo.py` | 8 条输入可跑；6 条核验输入为 ok；南京大学、星海路１３８号为 mock degraded |
| 四条离线评测 | jieba、jieba_lexicon、local_graph、mock 均完成，各 12 样例，0 个远端请求；报告在 reports/ |
| JSON Schema 与 Pydantic 比较、金标准加载 | lexicon/gold schema 一致，12 条金标准全文件校验通过 |
| `cmp docs/DESIGN.md /workspace/jev-chinese-ner-design.md` | 字节一致 |
| 常见凭据模式检查 | 代码、资产、测试、文档、环境示例未发现匹配；未写入或提交真实凭据 |

pytest 的一条警告来自 Starlette 对 AnyIO 已弃用别名的引用，不影响测试结果。

## 本次演示评测数值

| route | 单元整串正确率 | 单元跨度 F1 | 成分角色 Macro-F1 | gold 路径可达率 |
|---|---:|---:|---:|---:|
| jieba | 0.5000 | 0.5000 | 不适用 | 不适用 |
| jieba_lexicon | 0.8333 | 0.8261 | 0.7372 | 不适用 |
| local_graph | 1.0000 | 1.0000 | 0.7897 | 1.0000 |
| mock | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

这些是与词库强重叠的 12 条 demo 冒烟成绩。mock 使用合成概率；不得用该表宣称真实模型
性能、中文优越性或泛化效果。真实校准指标和账单成本未测量。角色 Macro-F1 包含预测或
标注中出现的角色，并要求父跨度/成分跨度/角色联合命中。

## 复现命令

```bash
cd /workspace/AGIworkspace/Jev-ChineseNER
uv sync --extra dev --frozen
uv run python scripts/demo.py
uv run jev-chinesener '南京市长江大桥' --dry-run
uv run jev-chinesener '星海路１３８号' --backend mock
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run jev-evaluate --route local_graph --split demo --output reports/local.json
uv build
uv run uvicorn jev_chinesener.api:app --host 127.0.0.1 --port 8000
```

另一个终端执行：

```bash
curl -s http://127.0.0.1:8000/v1/toponyms/segment \
  -H 'Content-Type: application/json' \
  -d '{"text":"上海市南京东路","granularity":"both","top_k":3}'
```

没有修改 `~/.codex/config.toml`，没有使用 Shepherd；工作目录无 `.git`，没有 commit/PR。
B/D 保留项及原因见 [GAP_AUDIT.md](GAP_AUDIT.md)，不影响本轮 A/C 工程验收。
