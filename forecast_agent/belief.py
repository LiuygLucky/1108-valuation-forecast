"""Numerical forecasts. LLMs never supply the six probabilities."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import norm

from forecast_agent.config import Settings
from forecast_agent.schemas import CognitiveState, MarketRules, NPMObservation, Probability


def map_intervals(samples: np.ndarray, rules: MarketRules) -> list[Probability]:
    if samples.ndim != 1 or len(samples) == 0 or not np.all(np.isfinite(samples) & (samples > 0)):
        raise ValueError("Samples must be finite positive valuations")
    result = []
    assigned = np.zeros(len(samples), dtype=int)
    for interval in rules.intervals:
        mask = samples >= interval.lower if interval.lower_closed else samples > interval.lower
        if interval.upper is not None:
            mask &= samples <= interval.upper if interval.upper_closed else samples < interval.upper
        assigned += mask
        result.append(Probability(interval=interval.label, probability=float(mask.mean())))
    if not np.all(assigned == 1):
        raise ValueError("Each sample must belong to exactly one interval")
    return result


def baseline_parameters(anchor: NPMObservation, rules: MarketRules, settings: Settings) -> dict:
    if anchor.effective_date > rules.target_date:
        raise ValueError("NPM anchor effective date is after the target date")
    horizon = (rules.target_date - anchor.effective_date).days / 365.25
    variance = settings.annual_volatility**2 * horizon + settings.anchor_log_uncertainty**2
    return {
        "years_from_anchor": horizon,
        "log_drift": settings.annual_log_drift * horizon,
        "log_sigma": float(np.sqrt(variance)),
    }


def baseline_samples(anchor: NPMObservation, rules: MarketRules, settings: Settings) -> np.ndarray:
    params = baseline_parameters(anchor, rules, settings)
    z = np.random.default_rng(settings.seed).standard_normal(settings.samples)
    return anchor.valuation_trillion * np.exp(params["log_drift"] + params["log_sigma"] * z)


def analytic_baseline(anchor: NPMObservation, rules: MarketRules, settings: Settings) -> list[float]:
    p = baseline_parameters(anchor, rules, settings)

    def cdf(x):
        if x is None:
            return 1.0
        if x == 0:
            return 0.0
        return float(norm.cdf((np.log(x / anchor.valuation_trillion) - p["log_drift"]) / p["log_sigma"]))

    return [cdf(i.upper) - cdf(i.lower) for i in rules.intervals]


def update_belief(state: CognitiveState, rules: MarketRules, settings: Settings) -> dict:
    if state.anchor is None:
        raise ValueError("A verified NPM anchor is required")
    anchor = state.anchor
    if (
        not anchor.verified
        or anchor.synthetic != (state.mode == "demo")
        or anchor.observed_at > state.as_of
        or anchor.source_url != rules.source_url
    ):
        raise ValueError("NPM anchor is not eligible for this forecast information set")
    base = baseline_samples(anchor, rules, settings)
    accepted = set(state.critique.accepted_evidence if state.critique else [])
    disputed = set(state.critique.disputed_evidence if state.critique else [])
    evidence = {e.evidence_id: e for e in state.evidence}
    used_clusters, adjustments, exclusions = set(), [], []
    anchor_close = datetime.combine(anchor.effective_date, time(23, 59, 59), ZoneInfo(rules.timezone))
    for hypothesis in state.hypotheses:
        candidates = [evidence[x] for x in hypothesis.evidence_ids if x in evidence]
        valid = [
            e
            for e in candidates
            if e.evidence_id in accepted
            and e.evidence_id not in disputed
            and not e.exclusion_reasons
            and not e.stale
            and e.supported
            and e.retrieval_verified
            and e.support_level == "direct"
            and e.event_status == "completed"
            and e.published_at
            and e.published_at > anchor_close
        ]
        if not valid or hypothesis.direction == "uncertain" or hypothesis.priced_in in {"yes", "unknown"}:
            exclusions.append(
                {
                    "event": hypothesis.event,
                    "reason": "No new accepted completed evidence, unclear direction, or priced-in/unknown",
                }
            )
            continue
        ev = sorted(valid, key=lambda e: (-e.credibility, e.evidence_id))[0]
        if ev.event_cluster in used_clusters:
            exclusions.append({"event": hypothesis.event, "reason": "Duplicate event cluster"})
            continue
        used_clusters.add(ev.event_cluster)
        # Fixed subjective effect magnitude, not a source-confidence probability.
        shift = settings.max_event_log_shift * (0.5 if hypothesis.priced_in == "partial" else 1.0)
        shift *= 1 if hypothesis.direction == "positive" else -1
        adjustments.append(
            {
                "event": hypothesis.event,
                "evidence_ids": [e.evidence_id for e in valid],
                "event_cluster": ev.event_cluster,
                "log_shift": shift,
                "priced_in": hypothesis.priced_in,
                "mechanism": hypothesis.mechanism,
            }
        )
    total = float(
        np.clip(
            sum(a["log_shift"] for a in adjustments),
            -settings.max_total_log_shift,
            settings.max_total_log_shift,
        )
    )
    shifts = [settings.scenario_down_log_shift, 0, settings.scenario_up_log_shift]
    scenario = np.random.default_rng(settings.seed + 1).choice(
        3, settings.samples, p=settings.scenario_weights
    )
    posterior = base * np.exp(np.asarray(shifts)[scenario] + total)
    histogram, edges = np.histogram(posterior, bins=60)
    scenario_only = base * np.exp(np.asarray(shifts)[scenario])
    return {
        "method": "Heuristic lognormal baseline + subjective scenario mixture + constrained evidence shifts",
        "calibrated": False,
        "seed": settings.seed,
        "samples": settings.samples,
        "prior_assumptions": baseline_parameters(anchor, rules, settings),
        "baseline_valuation": anchor.valuation_trillion,
        "baseline_source": anchor.model_dump(mode="json"),
        "baseline_distribution": [p.model_dump() for p in map_intervals(base, rules)],
        "analytic_baseline": analytic_baseline(anchor, rules, settings),
        "scenario_assumptions": {
            "labels": ["downside", "central", "upside"],
            "log_shifts": shifts,
            "weights": list(settings.scenario_weights),
        },
        "scenario_only_distribution": [p.model_dump() for p in map_intervals(scenario_only, rules)],
        "event_adjustments": adjustments,
        "excluded_adjustments": exclusions,
        "total_log_shift": total,
        "posterior_distribution": [p.model_dump() for p in map_intervals(posterior, rules)],
        "median": float(np.median(posterior)),
        "interval90": np.quantile(posterior, [0.05, 0.95]).tolist(),
        "histogram": {"counts": histogram.tolist(), "edges": edges.tolist()},
        "uncertainty_notes": [
            "Annual drift and volatility are configured estimates; their input series and estimation method "
            "are not archived in this run. Scenario weights and event magnitudes remain subjective.",
            "The full probability model has not been validated for out-of-sample calibration.",
            "Causal mechanisms are hypotheses, not identified causal effects.",
            "Source credibility is used for admission, never as an event probability.",
        ],
    }
