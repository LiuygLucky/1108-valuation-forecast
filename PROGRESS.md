# 实施与恢复记录

更新：2026-11-08（Asia/Singapore）。**400,000 token 余量和用户新参数已完成两轮真实 live 预测；详见 CHANGELOG.md。**

## 下次重连先读
1. 本文件、README.md、DESIGN.md、VALIDATION.md。任务书 prompt.md 末尾含密钥，不要再次输出。
2. 使用项目 .venv/Scripts/python.exe。检查当前实现后增量修改，不要从头覆盖。
3. 已完成预测与报告不可覆盖；新预测使用新 run_id。

## 已完成
- M1：配置、Pydantic、NPM 锚点、基准模型、真实 API、CLI 保存。
- M2：LangGraph 状态、规划、证据处理、FAISS、因果假设、独立审查、有界补搜。
- M3：受约束事件调整、情景混合、蒙特卡洛、基准对比、Markdown/JSON/SVG、历史/结算评分。
- M4：四页 Streamlit、CLI、README、配置示例、依赖锁定、AGENTS.md、完整演示。
- 最新测试：**43 passed in 16.18s**；Ruff 静态与格式检查通过。
- 审查修复：live 采集限 30 分钟；不同事件不因同日同类别合并；报告关键事实只列审查接受证据；历史比较排除自身。详见 CHANGELOG.md。既有真实预测与报告未改写。
- 证据质量增强：来源轨迹和内容核验、确定性来源分类、逐条支持审查、第一手判断、交叉来源候选和非概率质量分。`direct` 才能触发事件数值调整；旧运行显示未评估。详见 DESIGN.md 和 CHANGELOG.md。
- 真实联调后增加有界 Critique 输入、范围外 ID 安全排除、支持程度与 NPM 相关性分离、无直接证据时的基准回退、新 run_id 的 checkpoint 分叉。失败试验及修复过程完整记在 CHANGELOG.md。
- 节点、查询、预算预留均保存 SQLite checkpoint；查询中断、导出中断和预算耗尽均有恢复测试。

## 当前接口与数据
- LLM：qwen3.8-max；专属地址 https://ws-xwvcymtulfsz52le.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 已实际成功，.env 已切换。
- 北京共享端点也已验证；旧数字 8597379 拼接地址无效，旧错误不代表当前接口失败。
- 密钥只在用户原始 prompt.md 与被忽略的 .env。不要复制到源码、报告或版本控制。
- Qwen 默认显式关闭深度思考；可选 thinking_budget 计入 token/费用估算预留。
- Tavily 实际调用成功，网页全文和时间元数据保存在真实 SQLite。
- NPM 前端已由代理逐项视觉核对：OpenAI Valuation **1.272 万亿美元**，页面日期 **2026-11-05**。
- 观测时间 **2026-11-07T19:15:32.680Z**。原始截图、渲染 DOM、元数据在 data/npm_capture/。
- 锚点 ID：npm_d5000a28cbc540c4bdc5a6fe5550e5f6；存档副本与 SHA-256 在 data/live/archives/。
- 此锚点不是年底结算结果。目标日后必须确认最终有效观测；未确认时 UNRESOLVED，不评分。

## 新版真实预测（2026-11-08）
- **当前最新两轮 live 运行**：`run_f0f7880d0a594fb7b21b16ff59181742`，无父运行或恢复，as_of=`2026-11-08T00:51:04.221076Z`。`annual_log_drift=0.52`、`annual_volatility=0.22`、`max_tokens=400000` 均在不可变快照中。6 次真实 Tavily、7 次 Qwen；70 个来源、92 条审计证据、18 条最终审查证据（13 direct、5 partial），1 项事件调整，概率和 1.0，中位数约 1.4202 万亿美元。预留 295,615 / 400,000，完整报告在 `reports/run_f0f7880d0a594fb7b21b16ff59181742/`。
- 第二轮新增 6 条结构化证据，4 条进入最终审查并被接受；未增加合格事件调整，故概率与第一轮相同。`reports/latest_live.json` 已指向当前运行；上轮摘要在 `reports/summary_run_ec01d36e0a974ec08fd81f0482aca70b.json`。
- 参数敏感性对比：同一锚点、证据与随机种子下，仅从 0 / 0.45 改为 0.52 / 0.22，中位数约 1.3106→1.4202 万亿美元；见 `reports/parameter_sensitivity_run_ec01d36e0a974ec08fd81f0482aca70b.json`。用户称新参数来自历史序列，但原始序列和估计方法未归档核验；不得称已校准。
- **全新端到端 live 运行已完成**：`run_0aa2f323cf034dddad02064953ae3a1c`，无父运行、无恢复；as_of=`2026-11-08T00:35:50.688452Z`。真实 Qwen 4 次、Tavily 3 次；53 个来源、75 条审计证据、18 条逐条审查（15 direct、3 partial），1 项事件调整。六区间概率和 1.0，中位数约 1.4202 万亿美元。完整报告在 `reports/run_0aa2f323cf034dddad02064953ae3a1c/`。
- 上述前一完整运行的摘要曾为最新；原始 V1 摘要保存在 `reports/summary_run_12cedfca3dd34d378c387561ec201a02.json`。既有预测文件未覆盖。
- 完成运行：`run_b6e66683226a49548c9c09deec4c332f`，父运行 `run_9cef1ba049174b68ad3a1716dad1026e`；保留原 `as_of=2026-11-08T00:24:06.790270Z`。
- 父运行实际完成 Qwen 规划/抽取/Reason、三次 Tavily 搜索并保存来源；新运行复用该完整真实研究 checkpoint，重新成功调用 Qwen Critique，然后完成概率与报告。未再次调用 Tavily；既有用量继承。
- 51 个来源、68 条审计证据；18 条逐条审查，15 条直接支持、3 条部分支持，18 条均被接受。仅 1 项事件通过数值准入；其他档案证据保留但不默认接受。概率和 1.0，中位数约 1.3106 万亿美元。
- 报告与 JSON/SVG：`reports/run_b6e66683226a49548c9c09deec4c332f/`。旧完成预测和失败 checkpoint 未覆盖。live 检索晚于 as_of，不能当作严格历史隔离回测；NPM 年底结算尚未发生。

## 交付入口
- 真实报告：reports/run_12cedfca3dd34d378c387561ec201a02/report.md；同目录有预测 JSON、审计 JSON、概率 SVG。
- 原始 V1 真实摘要现存档为 `reports/summary_run_12cedfca3dd34d378c387561ec201a02.json`；当前最新真实摘要为 `reports/latest_live.json`。
- 28 个来源版本、17 条审查证据、13 条接受；正反分析齐全。概率总和 1.0，中位数约 1.3106 万亿美元。
- 第二轮补搜遇 token 硬上限，通过 resume 采用第一轮完整审查集计算；报告明确说明后续资料未作为新增依据。
- 离线报告：reports/run_33b233619a414faaaaec29dc12360d53/report.md；摘要 reports/latest_demo.json。
- 真实组件检查：reports/component_20261107T190045Z/，全部通过，1 条不支持引文自动排除。
- Dashboard：http://127.0.0.1:8501；进程 PID 记在 data/streamlit.pid，退出后按 README 启动。

## 继续运行
- 新真实预测：.venv/Scripts/python.exe main.py run --mode live
- 离线演示：.venv/Scripts/python.exe main.py run --mode demo
- 恢复未完成运行：.venv/Scripts/python.exe main.py resume <run_id> --mode live
- Dashboard：.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py
- 验证：.venv/Scripts/python.exe -m pytest -q

恢复须匹配原配置、模型、供应商和截止时间。规则/参数变化必须新建运行。历史模式只用当时已归档且公开的资料，禁止实时搜索。来源可信度不是事件概率。

最终界面验收：已重启后台服务清除开发期间旧 Schema 缓存，真实预测结果可见；进程 PID 更新到 data/streamlit.pid。窄窗口预测区间不再截断，界面测试 2 项再次通过。最终凭据扫描 66 个文本文件无泄漏。
