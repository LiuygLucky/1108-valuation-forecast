"""Historical comparison and resolution-gated proper scoring rules."""

import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

from forecast_agent.observations import archive_valid
from forecast_agent.schemas import Forecast, MarketRules, uid, utcnow
from forecast_agent.storage import Store


def compare_forecasts(previous: Forecast, current: Forecast) -> dict:
    if previous.rules_snapshot != current.rules_snapshot or previous.mode != current.mode:
        raise ValueError("Only forecasts with identical rules and data mode are comparable")
    previous_events = {x["event_cluster"]: x for x in previous.belief_state["event_adjustments"]}
    current_events = {x["event_cluster"]: x for x in current.belief_state["event_adjustments"]}
    changed = {
        k: {"previous": previous.settings_snapshot.get(k), "current": v}
        for k, v in current.settings_snapshot.items()
        if previous.settings_snapshot.get(k) != v
    }
    return {
        "previous_run": previous.run_id,
        "current_run": current.run_id,
        "probability_changes": [
            {"interval": p.interval, "delta": c.probability - p.probability}
            for p, c in zip(previous.probabilities, current.probabilities, strict=True)
        ],
        "new_evidence_ids": sorted(set(current.key_evidence_ids) - set(previous.key_evidence_ids)),
        "removed_evidence_ids": sorted(set(previous.key_evidence_ids) - set(current.key_evidence_ids)),
        "added_event_adjustments": [
            current_events[k] for k in current_events.keys() - previous_events.keys()
        ],
        "removed_event_adjustments": [
            previous_events[k] for k in previous_events.keys() - current_events.keys()
        ],
        "changed_event_adjustments": [
            {"previous": previous_events[k], "current": current_events[k]}
            for k in previous_events.keys() & current_events.keys()
            if previous_events[k] != current_events[k]
        ],
        "assumption_changes": changed,
        "anchor_changed": previous.belief_state["baseline_source"] != current.belief_state["baseline_source"],
        "horizon_changed": previous.belief_state["prior_assumptions"]
        != current.belief_state["prior_assumptions"],
        "interpretation": "Differences arise from anchors, time horizons, accepted events and explicit assumptions; not a causal attribution estimate.",
    }


def settle(
    store: Store,
    rules: MarketRules,
    observation_id: str | None,
    confirmed_latest: bool = False,
    observed_at=None,
) -> dict:
    now = observed_at or utcnow()
    update = datetime.combine(rules.target_date, time(rules.update_hour), ZoneInfo(rules.timezone))
    eligible = [
        o
        for o in store.observations()
        if o.verified
        and not o.synthetic
        and o.source_url == rules.source_url
        and o.effective_date <= rules.target_date
        and o.observed_at <= now
        and archive_valid(o)
    ]
    candidates = [o for o in eligible if o.observation_id == observation_id]
    result = {
        "settlement_id": uid("settlement"),
        "status": "UNRESOLVED",
        "rules": rules.model_dump(mode="json"),
        "settlement_observed_at": now.isoformat(),
        "settlement_effective_date": None,
        "reason": "Requires finality confirmation after target-day scheduled update and a qualified archived NPM observation",
    }
    if now >= update and confirmed_latest and candidates:
        chosen = candidates[0]
        latest = max(eligible, key=lambda o: (o.effective_date, o.observed_at))
        if chosen.observation_id != latest.observation_id:
            raise ValueError("Selected observation is not the latest qualifying observation in the archive")
        bucket = next(
            i for i, interval in enumerate(rules.intervals) if interval.contains(chosen.valuation_trillion)
        )
        result.update(
            status="RESOLVED",
            settlement_effective_date=chosen.effective_date.isoformat(),
            observation=chosen.model_dump(mode="json"),
            outcome_index=bucket,
            reason="Human confirmed final/latest eligible NPM observation as of target date",
        )
    import json

    with store.connect() as db:
        db.execute(
            "INSERT INTO settlements VALUES (?,?,?)",
            (result["settlement_id"], now.isoformat(), json.dumps(result, ensure_ascii=False)),
        )
    return result


def score(forecast: Forecast, settlement: dict) -> dict:
    if settlement["status"] != "RESOLVED":
        raise ValueError("UNRESOLVED settlements cannot be scored")
    if forecast.mode == "demo" or forecast.rules_snapshot != settlement["rules"]:
        raise ValueError("Real settlement requires a non-synthetic forecast with identical rules")
    outcome = settlement["outcome_index"]
    probabilities = [p.probability for p in forecast.probabilities]
    baseline = [p.probability for p in forecast.baseline_probabilities]

    def metrics(p):
        return {
            "brier_multiclass": sum((value - (i == outcome)) ** 2 for i, value in enumerate(p)),
            "log_loss": -math.log(p[outcome]) if p[outcome] > 0 else None,
            "log_loss_infinite": p[outcome] == 0,
        }

    return {
        "forecast": metrics(probabilities),
        "baseline": metrics(baseline),
        "note": "One settled event cannot establish calibration or forecasting skill.",
    }
