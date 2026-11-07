# 审查修复记录

## 2026-11-08：严格对照 prompt.md 的四项改进

### 1. live 时间窗口
- 问题：仅凭 `published_at <= as_of`，旧运行恢复后仍可能接纳很晚才检索的来源。
- 方案：冻结 `as_of`，限定 `retrieved_at` 在运行开始后的 30 分钟内；窗口到期的搜索明确报错并要求新 run_id。来源时间过滤保留在证据准入边界。
- 修改：`forecast_agent/evidence.py`、`forecast_agent/controller.py`、`README.md`。
- 验证：窗口内/窗口外来源和过期搜索定向测试；全套测试通过。
- 限制：live 仍是截止时间后采集，不能作为严格历史隔离回测。窗口到期后的网络故障恢复需要新运行。

### 2. 事件去重
- 问题：同实体、类别、日期和状态的独立事件会被合并。
- 方案：事件簇加入规范化主张；重复判定依据相同支持引文，或相同类别及状态下的高度相似主张；不再仅凭同日同类合并。
- 修改：`forecast_agent/evidence.py`。
- 验证：转载去重、跨类别相同引文、同日不同事件测试通过。
- 限制：短引文或高度相似主张仍可能误判，需人工检查审计记录；不重算既有预测。

### 3. 报告事实准入
- 问题：关键事实列表只检查程序性排除原因，未要求独立审查接受。
- 方案：该列表仅渲染审查接受且无排除原因的证据；争议证据仍在审查和排除部分保留可追溯性。
- 修改：`forecast_agent/report.py`。
- 验证：将已接受证据改为争议后的报告回归测试通过。

### 4. 历史比较选择
- 问题：Dashboard 可将同一运行与自身比较。
- 方案：比较候选列表排除当前选中的 run_id。
- 修改：`app/streamlit_app.py`。
- 验证：两次演示运行后的 Streamlit 交互测试通过。

### 检查与数据边界
- `.venv/Scripts/python.exe -m pytest -q`：33 passed。
- `.venv/Scripts/python.exe -m ruff check .`：通过。
- `.venv/Scripts/python.exe -m ruff format --check .`：通过。
- 未修改 SQLite 中的 checkpoint、已完成预测或既有报告；本轮未调用真实搜索和 LLM，不能宣称完成新代码的真实数据验收。
