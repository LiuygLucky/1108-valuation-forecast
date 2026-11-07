# Cognitive Forecasting Agent V1

基于 LangGraph 的认知研究与事件概率预测系统。固定问题：**OpenAI 在 2026-12-31 的 Nasdaq
Private Market（NPM）Valuation 落在哪个区间？** 金融估值是应用场景，系统重点是主动检索、
证据记忆、因果机制假设、反证审查、显式概率更新和可追溯记录。

## 快速运行（Windows / Python 3.12）

在项目根目录打开 PowerShell。本次交付已创建 `.venv`；新电脑安装方法：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

无需密钥的完整离线演示：

```powershell
.\.venv\Scripts\python.exe main.py run --mode demo
.\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

打开终端给出的本地地址（通常 http://localhost:8501），侧栏选择 **DEMO / SYNTHETIC 离线演示**，
点击“开始预测”。研究计划、搜索、正反证据、FAISS 检索、因果假设、反证、补搜、数值预测、
Markdown/JSON 报告和历史保存全部执行。演示来源使用 `.example.invalid`，不能作为现实事实。

开发期间若修改 Pydantic 状态 Schema，请重启 Streamlit 进程，避免旧模块缓存与新快照字段不一致。

结果保存在 `reports/<run_id>/`：

- `report.md`：可读研究报告。
- `forecast.json`：不可覆盖的预测快照，含完整规则和参数。
- `audit.json`：来源全文、证据、排除原因、假设、查询、预算及状态。
- `probabilities.svg`：无外部依赖的六区间概率图。

若需严格复现本机依赖，可先安装 `requirements-lock.txt`，再执行 `pip install -e . --no-deps`。

## 真实模式配置

没有 `.env` 时复制 `.env.example` 为 `.env`，填写：

```dotenv
LLM_API_KEY=<your-secret>
LLM_BASE_URL=<exact-provider-compatible-endpoint>
LLM_MODEL=qwen3.8-max
TAVILY_API_KEY=<your-secret>
```

默认主模型按任务书为 Qwen3.8-Max，接口采用 OpenAI-compatible Chat Completions。
DeepSeek 可改为 `LLM_BASE_URL=https://api.deepseek.com/v1` 和 `LLM_MODEL=deepseek-chat`。
模型名称和端点须以供应商实际开通的服务为准。**已实际验证专属端点
`https://ws-xwvcymtulfsz52le.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` + `qwen3.8-max` 可用，当前 `.env` 已配置该组合。**
北京共享端点 `https://dashscope.aliyuncs.com/compatible-mode/v1` 也已验证可用，可按需配置。
用户最初提供的工作空间专属地址返回 `Workspace endpoint is invalid`，保留在检查记录中。
如迁移至专属域名，请从控制台“API Host”复制完整地址，不能用其他控制台数字 ID 拼接。详情见 `VALIDATION.md`。

`.env` 已被 `.gitignore` 排除；不得把密钥填入 Python、YAML、报告或版本控制。
原始 `prompt.md` 含凭据，也被排除。应用不会自动读取任务书里的密钥。

真实接口检查（会调用一次 Tavily 和一次 LLM，可能产生少量供应商费用）：

```powershell
.\.venv\Scripts\python.exe scripts/check_providers.py
```

检查成功不等于真实预测完成。原始检索结果进入真实 SQLite，接口状态另存独立检查报告。
搜索失败不会静默进入演示模式；真实模式缺数据时明确报错。

## 导入唯一合格锚点：NPM Valuation

唯一目标页：
https://fe.secondmarket.com/companies/company-30839e0b-2730-4495-839f-1bf638fa9cca/data

在有权访问的 NPM 页面人工核对 **OpenAI / Valuation**，保存截图或网页档案。不能使用
融资新闻估值、企业价值、NPM Price 或别家二级市场的数字替代。应用不会绕过登录或访问控制。

1. 复制 `examples/npm_observation.template.json` 到自己的元数据文件。
2. 填入真实万亿美元值、数据生效业务日期、实际观测时间（必须带时区），核对后设 `verified=true`。
3. 导入元数据和截图/网页档案。程序复制存档到数据目录并计算 SHA-256；后续运行会重新验 hash。

```powershell
.\.venv\Scripts\python.exe main.py import-npm .\my_npm.json .\my_npm_capture.png
.\.venv\Scripts\python.exe main.py run --mode live
```

完整元数据示例见模板；模板故意保留 `null` 和 `verified=false`，不能直接当作观测导入。
人工确认不是自动事实识别：V1 校验来源 URL、指标、时间和存档完整性，无法自动验证截图中数字
是否抄录正确。请在 `notes` 中记录页面可见日期、单位换算与任何歧义。

本次交付已由代理逐项视觉核对真实 NPM 页面并导入：Valuation 为 1.272 万亿美元，页面标注
“As of Nov 5, 2026”，实际观测时间为 2026-11-07T19:15:32.680Z。原始截图、渲染 DOM 与
元数据位于 `data/npm_capture/`；完整性校验截图另存于 `data/live/archives/`。
这只是预测锚点，**不是最终结算结果**；年底仍需人工确认结算观测及最终性。

## 工作流与目录

```text
ParseQuestion → PlanResearch → Search → ProcessEvidence → RetrieveMemory
  → Reason → Critique → CheckInformationSufficiency
  → [bounded Search again] → UpdateBelief → GenerateForecast → GenerateReport → SaveRun
```

| 文件 | 职责 |
|---|---|
| `forecast_agent/schemas.py` | Pydantic 认知状态、来源、证据、假设、审查、锚点、预测 |
| `config.py` / `config/*.yaml` | 环境密钥、模型参数、六区间和固定结算规则 |
| `clients.py` | Tavily、兼容 LLM、API/token/费用预算和重试 |
| `research.py` / `evidence.py` | 规划、抽取、独立审查、引文/时间校验、转载去重 |
| `storage.py` / `memory.py` | SQLite 追踪和快照，FAISS 检索 |
| `controller.py` | LangGraph、有界补搜、节点与查询级 checkpoint |
| `belief.py` | 对数正态基准、受约束事件调整、情景混合和蒙特卡洛 |
| `report.py` | Markdown/JSON/SVG 与 Plotly 图表 |
| `evaluation.py` | 历史差异、结算、Brier / log loss 与基准比较 |
| `demo.py` | 独立且明确标记的合成来源和结构化 LLM fixture |
| `app/streamlit_app.py` | 固定目标四页 Dashboard |

默认检索器使用 HashingVectorizer 字符 n-gram + FAISS，适合无 GPU、无模型下载的普通电脑。
这是词法向量检索，**不是语义 embedding**。可安装 `pip install -e '.[embeddings]'` 并设置
`embedding_backend: sentence-transformers`，使用可配置的多语种 CPU embedding 模型。
向量索引每次从合格的 SQLite 证据重建，避免一个未做时间过滤的全局索引造成信息泄漏。

## 概率计算与解释

目标六区间在 `config/market_rules.yaml` 中定义，覆盖所有正值且无重叠：
`(0,0.85)`、`[0.85,1.00)`、`[1.00,1.15)`、`[1.15,1.30)`、`[1.30,1.45]`、`(1.45,+∞)`。
特别注意 **1.45 属于第五区间**。这是终点区间事件，不是到期前是否曾触及阈值。

```text
years = (target_date - anchor_effective_date) / 365.25
sigma_total = sqrt(annual_volatility² × years + anchor_log_uncertainty²)
baseline = anchor × exp(annual_log_drift × years + sigma_total × Z)
forecast = baseline × exp(scenario_shift + clipped_sum(event_log_shifts))
```

默认 50,000 个样本，随机种子 20261231；SciPy 解析 CDF 检查基础蒙特卡洛误差。
`baseline_distribution` 是无新闻的比较基准；`scenario_only_distribution` 单独记录主观情景贡献；
`posterior_distribution` 是情景与证据融合分布。后者只是字段名称，**不是经过数据校准的贝叶斯后验**。

事件进入数值更新必须同时满足：引文匹配、来源完整、时间合格、未过时、独立审查接受、非争议、
已完成事实、明确方向、在锚点有效日之后公开，且机制分析认为未完全计价。已计价程度未知则不调整。
同一事件簇最多调整一次，单事件和总幅度均限幅。来源可信度只用于准入/代表来源选择，绝不当事件概率。
事件簇采用保守日期/类别分组及文本相似检测，可能合并同日同类的不同事件；V2 可改善事件实体消歧。

波动率、漂移、情景权重和事件幅度均为明确主观假设；V1 没有训练、回测校准或预测准确率声明。
90% 区间是模型的估值预测区间，不是参数置信区间。因果机制是可追溯假设，不是无偏因果效应估计。

## 时序、历史与结算

全部内部时间戳转为 UTC；页面与业务日期用 `America/New_York` 自动 DST。
任务书中“全年 UTC-5”和“自动 DST”存在冲突，本实现选择明确指定的 IANA 时区；目标日为 EST，
13:00 ET 对应 18:00 UTC。来源分别保留 event_at / published_at / retrieved_at / effective_at。
日期不明的来源排除；模型提供的新闻发布时间不能覆盖 API 原始元数据。

**live**：点击时冻结公开信息截止点，本次检索的 retrieved_at 会晚于 as_of，明确标记不能作为严格历史回测。检索只允许在运行开始后的 30 分钟内完成；超过窗口的未完成搜索须新建 run_id 和当前截止时间。来源即使标称早于 as_of 公开，迟到检索也不能并入旧运行。
**historical**：只查询本地已归档证据，要求 published_at 和 retrieved_at 都不晚于 as_of，绝不实时搜索。
后来抓到的旧报道不能加入过去的历史信息集。LLM 本身可能有训练知识，提示词限制不能构成完整历史隔离证明；
V1 不宣称回测有效性或成绩。

```powershell
.\.venv\Scripts\python.exe main.py run --mode historical --as-of '2026-11-07T18:00:00Z'
.\.venv\Scripts\python.exe main.py history --mode demo
.\.venv\Scripts\python.exe main.py compare <older_run_id> <newer_run_id> --mode demo
```

真实和历史模式共享真实档案库 `data/live/forecast.sqlite3`；演示保存在 `data/demo/forecast.sqlite3`。
历史对比列出区间变化、新增/移除证据、事件调整、锚点与参数变化；不是精确的因果贡献分解。

结算在目标日预定更新后人工核对：若目标日未更新/不可得，采用截至目标日最后一次合格 NPM 观测。
观测时间可以晚于目标日，生效日期不可以。只有人工确认最终性且存档校验通过才 `RESOLVED`。
无法确认则 `UNRESOLVED`，不评分。

```powershell
.\.venv\Scripts\python.exe main.py settle
.\.venv\Scripts\python.exe main.py settle --observation-id <npm_id> --confirm-latest
.\.venv\Scripts\python.exe main.py score <run_id> <settlement_id> --mode live
```

## 中断后继续

开发进度见 `PROGRESS.md`，整体设计见 `DESIGN.md`。下次重连先读这两个文件，再运行测试。
运行时每个 LangGraph 节点、搜索轮次、单次查询和 API 预算预留均保存 SQLite checkpoint。

```powershell
.\.venv\Scripts\python.exe main.py resume <run_id> --mode demo
# 或 --mode live / --mode historical，须与原运行匹配
```

恢复保留原 as_of、模式、模型/供应商、规则和数值参数，不覆盖已经完成的预测。
中断中的网络调用无法保证 exactly-once；恢复可能重新调用该请求，但前次预算预留不返还，费用估计偏保守。
模型 Schema 错误或供应商失败会明确停止，可在修复外部条件后恢复。改变供应商地址/模型或规则必须新建运行。

若补搜中途触及 token 预算，`resume` 会恢复最后一轮完整审查过的证据与假设，保留全部检索记录和已用预算，
跳过后续模型调用并完成数值预测。报告注明所用审查轮次及未采用后续资料；没有完整审查则拒绝预测。
补搜前会参考本轮实际 token 预留量并留出余量，避免在明显预算不足时启动下一轮。

默认每次最多 2 轮、每轮 3 查询、8 次搜索 HTTP 请求（包括重试）、12 次 LLM 请求、180,000 token
保守预留上限。UTF-8 字节数作为输入 token 的保守上界。可选填写 `.env` 中每百万输入/输出 token
价格后启用完整美元估算；价格未知时只给已知部分费用，不冒充真实账单。保留调用数和 token 硬上限。

Qwen 默认显式关闭 `enable_thinking`，避免供应商默认深度思考导致结构化抽取超时或隐藏预算膨胀。
若在 YAML 开启 `qwen_enable_thinking`，必须同时限制 `qwen_thinking_budget`；预算预留计入该上限。
网页正文按主题相关段落摘录，并附原文偏移；原始全文不修改。`llm_timeout_seconds` 控制请求读取超时。

## 验证与可交付状态

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

测试临时文件限定在项目 `.pytest_tmp`，避免 Windows 系统临时目录权限问题。测试不会使用真实 API Key 发起网络调用。
覆盖 Schema、外部失败/重试、来源追踪、去重、最大循环、区间、归一、复现、SQLite 不可覆盖、
防前瞻、恢复、情景约束、结算边界及 Streamlit 完整点击流程。实际验收结果见 `VALIDATION.md`。

已完成能力：完整认知闭环、外部检索接口、显式状态与记忆、独立审查、有限补搜、可复现概率、
解释报告、Dashboard、历史/结算及断点恢复。真实数据报告以 API 可用和合格 NPM 数据为前提；未满足时明确列出缺项。

本次已完成真实预测：`reports/run_12cedfca3dd34d378c387561ec201a02/report.md`。
离线报告：`reports/run_33b233619a414faaaaec29dc12360d53/report.md`。详细验收结果、概率和限制见 `VALIDATION.md`。

V2 待优化：历史数据校准、语义事件消歧、更多估值模型、动态贝叶斯模型、因果识别/反事实、
时间滚动验证、校准曲线、信息价值驱动搜索和多模型比较。V1 不交易、不下注、不训练大模型。

官方接口参考：[LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api)、
[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、
[阿里云 Base URL](https://help.aliyun.com/zh/model-studio/base-url)。
