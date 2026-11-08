# V1 验收记录

## 2026-11-08 预算与新参数的真实运行
- 用户给定 `annual_log_drift=0.52`、`annual_volatility=0.22`。配置和预测快照一致；历史输入序列及估计方法未归档，故只验证配置生效与模型敏感性，不宣称历史估计经独立核验或完整概率校准。
- 300,000 预留上限的 `run_ec01d36e0a974ec08fd81f0482aca70b` 完成第一轮，预留 148,939；第二轮预计需求 326,599，提前停止。
- 400,000 上限的全新 `run_f0f7880d0a594fb7b21b16ff59181742` 完成两轮研究：6 次真实 Tavily、7 次真实 Qwen，最终预留 295,615/400,000，供应商 token 合计 102,168。70 来源、92 审计证据；第二轮新增 6 条，其中 4 条最终被审查接受。18 条最终逐条审查（13 direct、5 partial），1 项事件数值调整，六区间概率和 1.0，中位数约 1.4202 万亿美元；报告/JSON/SVG 已保存。
- 同一数据和随机种子下的参数敏感性：0 / 0.45 → 0.52 / 0.22，中位数约 1.3106 → 1.4202 万亿美元，最高区间 +11.944 个百分点。结果在 `reports/parameter_sensitivity_run_ec01d36e0a974ec08fd81f0482aca70b.json`，标记为反事实参数对比，非新预测。
- 自动检查：43 passed；Ruff 静态与格式检查通过。live 检索晚于 as_of，不是严格历史隔离回测；LLM 单价未知，美元成本估计不完整。

## 2026-11-08 新版真实数据运行检查
- **全新完整 live 运行** `run_0aa2f323cf034dddad02064953ae3a1c`：ParseQuestion→PlanResearch→3 次 Tavily Search→ProcessEvidence→RetrieveMemory→Reason→Qwen Critique→UpdateBelief→GenerateForecast→GenerateReport→SaveRun 全部成功；无父运行或人工恢复。53 个来源、75 条审计证据，18 条审查证据（15 direct、3 partial），1 项事件调整，六区间概率和 1.0，中位数约 1.4202 万亿美元。
- 全新运行的报告、forecast.json、audit.json、probabilities.svg 已落盘，`reports/latest_live.json` 已更新；旧最新摘要另存档，历史预测文件未覆盖。
- 最终代码检查：`.venv/Scripts/python.exe -m pytest -q` 为 **42 passed in 19.18s**；`ruff check .` 与 `ruff format --check .` 均通过。
- `run_b6e66683226a49548c9c09deec4c332f` 状态 COMPLETE，来源运行 `run_9cef1ba049174b68ad3a1716dad1026e`。父运行真实调用 Qwen 和 Tavily，完成规划、三次搜索、抽取与 Reason；新运行在同一数据截止点重新真实调用 Qwen Critique，并完成数值与不可覆盖报告。
- 51 个来源、68 条审计证据；18 条经逐条审查，15 条 direct、3 条 partial；来源轨迹不合格的旧记录未通过准入。1 项直接支持事件进入数值调整，概率和为 1.0，中位数约 1.3106 万亿美元。
- 原始研究与最终预测分别有 checkpoint；最终报告、forecast.json、audit.json、probabilities.svg 位于 `reports/run_b6e66683226a49548c9c09deec4c332f/`。另有零事件调整的真实基准回退运行 `run_a686600ec2684c70a27b0e4558f8e3d1`。
- 未宣称严格历史隔离回测或年底 NPM 结算。API 价格未知，美元费用估计不完整；失败联调和修复详见 `CHANGELOG.md`。

## 2026-11-08 证据质量增强后的代码验证
- 新增来源轨迹/内容 hash、支持程度、缺失审查、交叉来源候选和来源类型回归测试；全套 pytest **38 passed**，Ruff 检查与格式检查通过。
- 使用合成演示运行验证新工作流。未重新执行真实 Tavily/LLM 预测；下方原始真实报告是增强前的历史成果，不代表新版机制真实验收。
- 既有预测、报告和 checkpoint 未覆盖，详情见 `CHANGELOG.md`。

验收日期：2026-11-08（Asia/Singapore）。源码、离线闭环与一次真实数据预测均已完成。

## 功能与测试
- Python 3.12.7 本地虚拟环境，requirements-lock.txt 保存依赖版本。
- 四阶段实现完成：基准闭环、认知研究、概率与报告、Dashboard 集成。
- **30 passed in 12.92s**；Ruff 静态与格式检查通过。
- 覆盖 Schema、API 失败/重试、预算、去重、引文与时序、概率边界/归一/复现、历史不可覆盖、查询中断恢复、报告导出中断恢复、预算耗尽恢复、结算和 Streamlit 按钮流程。
- Dashboard：http://127.0.0.1:8501；健康检查 200 / ok，浏览器页面已实际检查。

## 真实接口与原始观测
- Tavily 实际请求成功，真实网页及检索元数据存于 data/live/forecast.sqlite3。
- 正确专属端点：https://ws-xwvcymtulfsz52le.cn-beijing.maas.aliyuncs.com/compatible-mode/v1；qwen3.8-max 已验证，当前 .env 已配置。北京共享端点也已验证成功。
- 早期数字 ID 拼接端点失败；Qwen 默认深度思考曾导致抽取超时，现已默认显式关闭。失败记录保留为诊断历史。
- NPM 的 HTTP 静态页面只有应用外壳；浏览器前端加载后成功显示 **OpenAI / Valuation $1.272T / As of Nov 5, 2026**。
- 观测时间：2026-11-07T19:15:32.680Z。核验方式：代理对照渲染页面逐项视觉核验，不是用户人工签署确认。每股价格是另一字段，没有用于估值锚点。
- 原始截图、渲染 DOM、元数据：data/npm_capture/；截图副本及 SHA-256：data/live/archives/。
- 这是预测锚点，**不是目标日结算**；年底仍需人工确认最终性。

## 完整真实预测
运行 ID：run_12cedfca3dd34d378c387561ec201a02，状态 COMPLETE，模式 live。

- 信息截止：2026-11-07T19:16:44.539878Z（新加坡 2026-11-08 03:16:44）。
- 28 个归档来源版本，17 条用于本次审查的结构化证据；13 条接受、4 条争议/排除。
- 覆盖融资、估值、收入、盈利/成本、技术、监管；分析包含正面、负面和不确定方向。
- 6 次真实搜索、5 次真实 LLM 调用；供应商返回 44,834 输入 token 和 7,825 输出 token。
- 第二轮补搜触及保守 token 预留上限，没有扩大预算；通过恢复采用第一轮完整审查集计算。后续检索留档，但不作为新增数值依据。该限制明确写在报告与 checkpoint 中。
- 固定种子 20261231，50,000 样本，概率和 1.0；这是未校准的启发式模型，不是经过历史数据校准的贝叶斯后验。
- LLM 单价未配置，费用记录仅为已知部分估算，不能当作实际账单总额。

| 区间（万亿美元） | 概率 |
|---|---:|
| (0, 0.85) | 2.990% |
| [0.85, 1.00) | 9.148% |
| [1.00, 1.15) | 16.588% |
| [1.15, 1.30) | 19.908% |
| [1.30, 1.45] | 17.850% |
| (1.45, +∞) | 33.516% |

中位数 1.3106 万亿美元；90% 模型预测区间 [0.8959, 1.9264]，不是参数置信区间。

报告：reports/run_12cedfca3dd34d378c387561ec201a02/report.md；同目录 forecast.json、audit.json、probabilities.svg。摘要：reports/latest_live.json。

## 离线与组件记录
- 离线报告：reports/run_33b233619a414faaaaec29dc12360d53/report.md；DEMO / SYNTHETIC 标记完整，2 轮研究，概率和 1.0，API 费用 0。
- 真实组件检查：reports/component_20261107T190045Z/，5 个阶段通过，6 条抽取证据中 1 条引文不匹配被排除。
- 专属端点记录：reports/workspace_endpoint_check.json；共享端点记录：reports/shared_endpoint_check.json。

## 不宣称的能力
无历史校准、无准确率/回测成绩、无严格因果识别、无交易执行。实时检索时间晚于 as_of，已标明不能当作严格历史隔离回测。V2 改善参数校准、事件消歧、成本定价与研究调度。
