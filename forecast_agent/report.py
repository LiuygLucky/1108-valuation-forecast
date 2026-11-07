"""Deterministic report rendering: every substantive claim links to archived sources."""

import html
import json
import os
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from forecast_agent.schemas import CognitiveState, Forecast


def make_forecast(state, rules, settings):
    belief = state.belief_state
    return Forecast(
        run_id=state.run_id,
        question=state.question,
        as_of=state.as_of,
        target_date=rules.target_date,
        valuation_metric=rules.valuation_metric,
        market_rules_source=rules.source_url,
        model_version=settings.model_version,
        mode=state.mode,
        probabilities=belief["posterior_distribution"],
        baseline_probabilities=belief["baseline_distribution"],
        median_valuation=belief["median"],
        confidence_interval_90=belief["interval90"],
        key_evidence_ids=state.critique.accepted_evidence if state.critique else [],
        main_assumptions=[
            "NPM is the only valuation metric; financing headlines are not settlement values.",
            "Lognormal baseline; subjective downside/central/upside scenario mixture.",
            "Only new, completed, accepted, unpriced/partially priced events can shift the distribution.",
        ],
        limitations=belief["uncertainty_notes"] + state.warnings,
        belief_state=belief,
        rules_snapshot=rules.model_dump(mode="json"),
        settings_snapshot=settings.model_dump(mode="json"),
    )


def probability_chart(forecast: Forecast):
    fig = go.Figure()
    for title, points in [
        ("Financial baseline", forecast.baseline_probabilities),
        ("Evidence + scenarios", forecast.probabilities),
    ]:
        fig.add_bar(name=title, x=[p.interval for p in points], y=[p.probability for p in points])
    fig.update_layout(
        barmode="group",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        yaxis_tickformat=".0%",
        xaxis_title="NPM Valuation (USD trillion)",
        yaxis_title="Probability",
        title="DEMO / SYNTHETIC" if forecast.mode == "demo" else "Terminal forecast",
    )
    return fig


def distribution_chart(forecast: Forecast):
    h = forecast.belief_state["histogram"]
    centers = [(a + b) / 2 for a, b in zip(h["edges"][:-1], h["edges"][1:], strict=True)]
    fig = go.Figure(go.Bar(x=centers, y=h["counts"]))
    fig.update_layout(xaxis_title="NPM Valuation (USD trillion)", yaxis_title="Monte Carlo samples")
    return fig


def probability_svg(forecast: Forecast) -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="820" height="350" viewBox="0 0 820 350">',
        '<rect width="820" height="350" fill="#f8fafc"/>',
        '<g font-family="Arial,sans-serif" font-size="14" fill="#172554">',
        f'<text x="24" y="28">{html.escape("DEMO / SYNTHETIC — " if forecast.mode == "demo" else "")}'
        "NPM terminal valuation probabilities (USD trillion)</text>",
    ]
    for i, p in enumerate(forecast.probabilities):
        y = 57 + i * 45
        parts.extend(
            [
                f'<text x="24" y="{y + 18}">{html.escape(p.interval)}</text>',
                f'<rect x="170" y="{y}" width="{p.probability * 530:.2f}" height="27" rx="3" fill="#2563eb"/>',
                f'<text x="{180 + p.probability * 530:.2f}" y="{y + 19}">{p.probability:.2%}</text>',
            ]
        )
    return "\n".join(parts + ["</g></svg>"])


def markdown_report(state: CognitiveState) -> str:
    f = state.forecast
    if not f:
        raise ValueError("Forecast required before report")
    sources = {s.source_id: s for s in state.sources}

    def cite(e):
        return ", ".join(f"[{sid}]({sources[sid].url})" for sid in e.source_ids if sid in sources)

    mode = (
        "DEMO / SYNTHETIC — 全部数据为合成测试，不能作为真实预测"
        if state.mode == "demo"
        else state.mode.upper()
    )
    lines = [
        f"# Cognitive Forecasting Agent V1 — {mode}",
        "",
        f"运行：`{state.run_id}`",
        "",
        "## 预测问题与结算口径",
        "",
        f.question,
        "",
        f"信息截止：{state.as_of.isoformat()}（UTC）；{state.as_of.astimezone(ZoneInfo('America/New_York')).isoformat()}（ET）。",
        f"目标日期：{f.target_date}；单位：USD trillion；模型：{f.model_version}。",
        f"唯一结算指标：[{f.valuation_metric}]({f.market_rules_source})。这是假定终点估值，不是期间触及阈值。",
        "目标日 13:00 ET 更新后人工确认最终可见值；缺失时采用截至目标日最后一次合格观测；无法确认则 UNRESOLVED。",
        "所有内部时间为带时区 UTC；业务展示为 America/New_York（自动 DST）。",
        "",
        "## 当前关键事实 / 报道",
        "",
    ]
    accepted = set(state.critique.accepted_evidence) if state.critique else set()
    for e in state.evidence:
        if e.evidence_id in accepted and not e.exclusion_reasons:
            lines.append(
                f"- **{e.epistemic_status}** `{e.evidence_id}`：{e.claim}；状态 `{e.event_status}`；{cite(e)}。"
            )
    lines += ["", "## 正面因素、负面因素与因果假设", "", "以下仅为 Model Inference；没有进行严格因果识别。"]
    for h in state.hypotheses:
        lines += [
            f"\n### {h.event}",
            f"方向：{h.direction}；已计价：{h.priced_in}。",
            "机制：" + " → ".join(h.mechanism),
            "依据：" + ", ".join(h.evidence_ids),
            "中间变量：" + "；".join(h.intermediate_variables),
            "相反解释：" + "；".join(h.counterarguments),
            "不确定性：" + "；".join(h.uncertainties),
            "变化触发器：" + "；".join(h.change_triggers),
        ]
    lines += ["", "## 独立反证审查与信息缺口", ""]
    if state.critique:
        lines += [
            "接受：" + ", ".join(state.critique.accepted_evidence),
            "争议：" + ", ".join(state.critique.disputed_evidence),
            "潜在偏差：" + "；".join(state.critique.potential_biases),
        ]
    lines += ["- " + x for x in state.information_gaps]
    lines += ["", "## 排除的证据 / 调整", ""]
    for e in state.evidence:
        if e.exclusion_reasons or e.stale:
            lines.append(
                f"- `{e.evidence_id}`：{'；'.join(e.exclusion_reasons)}"
                f"{'；过时证据' if e.stale else ''}；{cite(e)}"
            )
    for exclusion in f.belief_state["excluded_adjustments"]:
        lines.append(f"- {exclusion['event']}：{exclusion['reason']}")
    lines += [
        "",
        "## 概率分布与可比较基准",
        "",
        "| 估值区间（万亿美元） | Financial Baseline | 情景与证据融合 |",
        "|---|---:|---:|",
    ]
    for base, posterior in zip(f.baseline_probabilities, f.probabilities, strict=True):
        lines.append(f"| {posterior.interval} | {base.probability:.2%} | {posterior.probability:.2%} |")
    lines += [
        "",
        "概率使用完整精度计算，表中四舍五入可能造成显示加总的微小差异。",
        "",
        "![概率分布](probabilities.svg)",
        "",
        "## 数值依据与当前结论",
        "",
        f"中位数 {f.median_valuation:.4f} 万亿美元；90% 模型预测区间 "
        f"[{f.confidence_interval_90[0]:.4f}, {f.confidence_interval_90[1]:.4f}]。该区间不是参数估计的置信区间。",
        "这是未校准的启发式预测，不能从来源可靠程度推断事件发生概率。",
        "公式：V_T = V_anchor × exp(mu × years + sigma_total × Z + scenario_shift + bounded_event_shift)。",
        "基准与更新模型共享基础随机数；情景贡献、事件贡献分别记录，方便做消融对比。",
        "",
        "```json",
        json.dumps(
            {k: v for k, v in f.belief_state.items() if k != "histogram"}, ensure_ascii=False, indent=2
        ),
        "```",
        "",
        "## 限制与运行预算",
        "",
    ]
    lines += ["- " + x for x in f.limitations]
    lines += [
        f"- 研究轮数：{state.iteration_count}；用于预测的完整审查轮次：{state.review_iteration}",
        "- Usage：" + json.dumps(state.usage.model_dump(), ensure_ascii=False),
        "- 成本为配置价格的保守估算；缺少供应商价格时不代表账单总额。",
        "",
        "## 来源与时间追溯",
        "",
    ]
    for s in state.sources:
        lines += [
            f"- [{s.title}]({s.url}) — `{s.source_id}`；published_at={s.published_at}；"
            f"retrieved_at={s.retrieved_at}；hash={s.content_hash}；date_provenance={s.date_provenance}。"
        ]
    lines += [
        "",
        "## 搜索与研究记录",
        "",
        "```json",
        json.dumps(state.search_history, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines) + "\n"


def export_report(state: CognitiveState, root: Path) -> Path:
    directory = root / state.run_id
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "report.md": state.report,
        "forecast.json": state.forecast.model_dump_json(indent=2),
        "audit.json": state.model_dump_json(indent=2),
        "probabilities.svg": probability_svg(state.forecast),
    }
    for filename, content in files.items():
        target = directory / filename
        if target.exists():
            if target.read_text("utf-8") != content:
                raise ValueError("Refusing to overwrite report artifact: " + filename)
        else:
            # Publish only a fully flushed file; hard-link creation cannot overwrite a snapshot.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_text("utf-8") != content:
                    raise ValueError("Concurrent report artifact mismatch: " + filename) from None
            finally:
                temporary.unlink(missing_ok=True)
    return directory
