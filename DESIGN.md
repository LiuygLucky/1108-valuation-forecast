# V1 设计与约束

固定终点问题 → LangGraph CognitiveState → 研究计划 → Tavily → 原始来源库 →
Pydantic 证据 → SQLite + FAISS 检索 → 因果假设 → 独立反证 → 有限补搜 →
NPM Financial Baseline → 受约束情景融合 → 数值概率 → Markdown / JSON → 不可覆盖历史。

## 技术选择
Python 3.12；LangGraph 显式状态图；Pydantic 边界校验；httpx 调用兼容 Chat Completions
接口（Qwen 主用，可切换 DeepSeek）；Tavily 真实搜索；SQLite WAL 本地事务；FAISS CPU。
默认 HashingVectorizer 为无需下载的词法向量检索，明确不是语义 embedding；可切换
sentence-transformers 多语种本地模型。NumPy / SciPy 可复现蒙特卡洛；Streamlit / Plotly。

## 数据接口
- Source：原始全文/摘要、URL、query、published_at、retrieved_at、内容 hash、模式。
- Evidence：source_ids、逐字支持引文、事件/公开/有效时间、类别、状态、事实层级、机制、去重簇。
- NPMObservation：唯一指标、美元万亿值、生效日期、观测时间、存档 hash 和原件、人工确认。
- Hypothesis：证据 ID、机制链、中间变量、反方解释、已计价程度、剩余不确定性。
- Critique：接受/争议证据、缺口、偏差、后续查询。
- CognitiveState：run_id、mode、as_of、计划、来源和证据、假设、审查、预算、搜索历史、
  iteration_count、belief_state、forecast、warnings。各节点后保存完整状态及 next_node。
- Forecast：规则快照、配置快照、基准/更新概率、分位数、数值参数、证据和模型版本。

## 数值方法
V_T = V_anchor × exp(mu × years + sigma_total × Z + scenario_shift + bounded_event_shift)。
sigma_total 包含从锚点有效日期到终点的扩散和观测不确定性。共享随机数对比基准与新闻模型。
事件只在独立审查接受、有来源支持、非重复、非陈旧、非争议且符合时序时参与。
方向由证据机制提出，幅度由配置中的主观启发式上限约束；单事件、全局均限幅。
可信度只控制证据准入，不充当事件概率。情景权重为明确的主观假设，不冒充校准后验。

## 时间与结算
UTC aware 内存和持久化；America/New_York 展示和业务日期（自动 DST）。原任务中固定 UTC-5
与自动 DST 冲突，采用明确指定的 IANA 时区；12 月 31 日为 EST，不影响目标日规则。
实时运行在检索开始后冻结信息截止点；后检索资料只可在本次 live 采集窗口按已知发布时间准入，
不能用于过去回测。历史模式严格要求 retrieved_at <= as_of，缺日期者排除。
预测 as_of 之后的事实、未核验引文、伪造 source_id 均排除。融资不是 NPM。
结算必须显式选择截至目标日最后一次合格观测，并人工确认可用性/最终性；否则 UNRESOLVED。

## 工程风险
- API/密钥/模型可用性：显式配置、有限重试、可读失败、仅显式 DEMO 合成模式。
- NPM 登录/缺数据：人工导入存档，不绕过访问限制，不替换结算指标。
- LLM 幻觉与注入：网页只作为数据；严格 Schema、引文比对、来源 ID 白名单、独立审查。
- 时间泄漏：证据和原始来源双层时间过滤；历史不调用实时搜索。
- 重复消息：URL/内容 hash 去重、事件簇和机制去重、总体限幅。
- 费用：调用/轮数/token 硬上限；已知价格时成本上限；未知价格时明确估算不完整。
- 中断：每节点 SQLite checkpoint；恢复同一模式、配置和截止时间，不覆盖已完成预测。

接口参考：[LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api)、
[Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search)。
