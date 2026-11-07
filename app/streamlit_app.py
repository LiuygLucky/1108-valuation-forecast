"""Fixed-target dashboard. Run: python -m streamlit run app/streamlit_app.py"""

import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from forecast_agent.config import ROOT, load_rules
from forecast_agent.controller import Controller
from forecast_agent.evaluation import compare_forecasts
from forecast_agent.report import distribution_chart, probability_chart
from forecast_agent.storage import Store

st.set_page_config(page_title="认知事件预测 · OpenAI", page_icon="◈", layout="wide")
rules = load_rules()
st.title("OpenAI 2026 年末 · 认知概率预测")
st.caption("固定终点任务 · NPM Valuation · 六区间概率 · 可追溯证据")
mode_label = st.sidebar.radio("数据模式", ["真实预测", "DEMO / SYNTHETIC 离线演示"])
mode = "demo" if mode_label.startswith("DEMO") else "live"
if mode == "demo":
    st.warning("DEMO / SYNTHETIC：本模式的来源、事件和 NPM 锚点全部是合成测试数据，不代表真实预测。")
data_root = Path(os.environ.get("FORECAST_DATA_DIR", str(ROOT / "data")))
report_root = Path(os.environ.get("FORECAST_REPORTS_DIR", str(ROOT / "reports")))
store = Store(data_root / mode / "forecast.sqlite3")
history = store.history(mode)
state = st.session_state.get("forecast_state")
if state and state.mode != mode:
    state = None
if state is None and history:
    state = store.saved_state(history[0].run_id)

task_tab, research_tab, result_tab, history_tab = st.tabs(
    ["预测任务", "认知研究过程", "预测结果", "预测历史"]
)

with task_tab:
    st.subheader(rules.question)
    col1, col2, col3 = st.columns(3)
    col1.metric("目标日期", str(rules.target_date))
    col2.metric("单位", "万亿美元")
    col3.metric("概率区间", "6")
    st.write(f"唯一指标：[Nasdaq Private Market Valuation]({rules.source_url})")
    st.write("信息截止时间将在点击预测时冻结；屏幕显示美国东部时间，底层保存带时区 UTC。")
    st.caption(
        "预定更新：13:00 America/New_York。结算必须人工确认目标日最终可见值或截至目标日最后一次合格观测。"
    )
    st.dataframe(
        pd.DataFrame({"估值区间（万亿美元）": [i.label for i in rules.intervals]}),
        hide_index=True,
        width="stretch",
    )
    if mode == "live":
        observations = [o for o in store.observations() if not o.synthetic]
        if observations:
            latest = max(observations, key=lambda o: (o.effective_date, o.observed_at))
            st.info(
                f"已导入 NPM 观测：{latest.effective_date} / {latest.valuation_trillion:.4f} 万亿美元；运行时将再校验时间和存档。"
            )
        else:
            st.info(
                "尚无 NPM 锚点。按 README 使用 import-npm 导入人工核验的元数据及截图/网页存档后，即可一键预测。"
            )
    if st.button("开始预测", type="primary", width="stretch"):
        progress = st.empty()
        controller = Controller(
            store,
            reports=report_root,
            on_progress=lambda name, s: progress.info(
                f"{name} · 第 {s.iteration_count} 轮 · 证据 {len(s.evidence)} 条"
            ),
        )
        run_state = controller.create_state(mode)
        st.session_state["last_run_id"] = run_state.run_id
        try:
            with st.spinner("正在执行有界认知研究工作流…"):
                state = controller.run(run_state)
            st.session_state["forecast_state"] = state
            progress.success("预测、报告和不可覆盖历史已保存")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
            st.code(f"python main.py resume {run_state.run_id} --mode {mode}")
    st.caption("运行失败时会保留已完成节点、证据和预算记录；可用 CLI 恢复。")

with research_tab:
    if state:
        st.write(f"Run ID：`{state.run_id}` · 研究轮数：{state.iteration_count}")
        st.subheader("研究计划与搜索")
        st.dataframe(
            pd.DataFrame([p.model_dump() for p in state.research_plan]), hide_index=True, width="stretch"
        )
        st.json(state.search_history, expanded=False)
        st.subheader("证据与排除原因")
        evidence_rows = [
            {
                "id": e.evidence_id,
                "类别": e.category,
                "事实层级": e.epistemic_status,
                "事件状态": e.event_status,
                "主张": e.claim,
                "发布时间": str(e.published_at),
                "排除原因": "; ".join(e.exclusion_reasons),
                "过时": e.stale,
                "来源ID": ", ".join(e.source_ids),
            }
            for e in state.evidence
        ]
        st.dataframe(pd.DataFrame(evidence_rows), hide_index=True, width="stretch")
        for source in state.sources:
            with st.expander(f"{source.title} · {source.source_id}"):
                st.write(source.url)
                st.write(f"published_at={source.published_at} / retrieved_at={source.retrieved_at}")
                st.text(source.content[:12000])
        st.subheader("因果机制假设（非严格因果识别）")
        for h in state.hypotheses:
            with st.expander(f"{h.direction} · {h.event}"):
                st.json(h.model_dump())
        st.subheader("独立反证审查")
        st.json(state.critique.model_dump() if state.critique else {})
        st.subheader("状态轨迹与预算")
        st.dataframe(pd.DataFrame(store.trace(state.run_id)), hide_index=True, width="stretch")
        st.json(state.usage.model_dump())
    else:
        st.info("完成一次预测后展示研究全过程。")

with result_tab:
    if state and state.forecast:
        forecast = state.forecast
        st.caption(
            f"截止时间 ET：{forecast.as_of.astimezone(ZoneInfo(rules.timezone)).isoformat()} · {forecast.model_version}"
        )
        cols = st.columns(3)
        cols[0].metric("估值中位数（万亿美元）", f"{forecast.median_valuation:.3f}")
        cols[1].caption("90% 模型预测区间（万亿美元）")
        cols[1].markdown(
            f"**{forecast.confidence_interval_90[0]:.3f} – {forecast.confidence_interval_90[1]:.3f}**"
        )
        cols[2].metric("概率合计", f"{sum(p.probability for p in forecast.probabilities):.2%}")
        st.plotly_chart(probability_chart(forecast), width="stretch")
        st.plotly_chart(distribution_chart(forecast), width="stretch")
        st.warning("这是未校准的启发式分布。波动率、情景权重和事件幅度是显式主观假设。")
        st.subheader("情景和受约束事件调整")
        st.json(
            {
                k: forecast.belief_state[k]
                for k in ["scenario_assumptions", "event_adjustments", "excluded_adjustments"]
            }
        )
        st.subheader("主要不确定性与变化触发器")
        for note in dict.fromkeys(forecast.limitations + state.information_gaps):
            st.write("• " + note)
        for h in state.hypotheses:
            st.write(f"{h.event}：" + "；".join(h.change_triggers))
        st.download_button(
            "下载 Markdown 报告", state.report, file_name=f"{state.run_id}.md", mime="text/markdown"
        )
        st.download_button(
            "下载 JSON 预测",
            forecast.model_dump_json(indent=2),
            file_name=f"{state.run_id}.json",
            mime="application/json",
        )
        st.download_button(
            "下载完整审计记录",
            state.model_dump_json(indent=2),
            file_name=f"{state.run_id}_audit.json",
            mime="application/json",
        )
    else:
        st.info("预测成功后展示六区间分布、基准对比和可下载报告。")

with history_tab:
    history = store.history(mode)
    if history:
        rows = [
            {
                "run_id": f.run_id,
                "as_of_ET": f.as_of.astimezone(ZoneInfo(rules.timezone)).isoformat(),
                "model": f.model_version,
                **{p.interval: p.probability for p in f.probabilities},
            }
            for f in history
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        selected = st.selectbox("查看历史运行", [f.run_id for f in history])
        if st.button("载入所选预测"):
            st.session_state["forecast_state"] = store.saved_state(selected)
            st.rerun()
        if len(history) >= 2:
            comparison_ids = [f.run_id for f in history if f.run_id != selected]
            older = st.selectbox("与其他运行比较", comparison_ids)
            st.json(
                compare_forecasts(store.saved_state(older).forecast, store.saved_state(selected).forecast)
            )
    else:
        st.info("当前模式尚无预测历史。真实数据与合成数据分别保存。")
