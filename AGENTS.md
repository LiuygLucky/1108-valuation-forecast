# 项目工作约定

- 需求来源为 `prompt.md`。其中有用户提供的密钥，读取需求时避免再次输出 API 凭据段。
- 接续本项目先读 `PROGRESS.md`、`DESIGN.md` 和 `VALIDATION.md`，检查当前代码和测试后增量修改。
- 用户明确要求中断可恢复：修改完成后更新 `PROGRESS.md`；保留运行 checkpoint 和已完成预测。
- 使用项目内 `.venv/Scripts/python.exe`；运行 `pytest -q`、`ruff check .` 和 `ruff format --check .`。
- 真实数据、合成演示、接口检查三者必须区分。没有合格 NPM 观测不得用融资估值替代。
- `.env` 与 `prompt.md` 含敏感内容，不能提交、复制到报告或输出至日志。
- 已完成预测不可覆盖。新行为/参数使用新 run_id；修复外部条件可从未完成节点恢复。
- 不应把网络或登录数据缺失描述为“真实验收完成”。
