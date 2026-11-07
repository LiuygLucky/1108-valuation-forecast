from datetime import UTC, datetime

import httpx
import pytest

from forecast_agent.belief import update_belief
from forecast_agent.clients import Budget, BudgetExceeded, TavilySearch
from forecast_agent.config import Secrets, load_rules, load_settings
from forecast_agent.controller import Controller
from forecast_agent.demo import DemoSearch
from forecast_agent.evaluation import compare_forecasts, score
from forecast_agent.schemas import Usage
from forecast_agent.storage import Store


def demo_run(tmp_path):
    store = Store(tmp_path / "demo.db")
    c = Controller(store, reports=tmp_path / "reports")
    return c.run(c.create_state("demo"))


def test_source_credibility_is_not_probability_and_duplicate_has_no_weight(tmp_path):
    state = demo_run(tmp_path)
    settings, rules = load_settings(), load_rules()
    first = update_belief(state, rules, settings)
    for ev in state.evidence:
        ev.credibility = 0.7
    second = update_belief(state, rules, settings)
    assert first["posterior_distribution"] == second["posterior_distribution"]
    state.hypotheses += [state.hypotheses[0].model_copy(deep=True)]
    third = update_belief(state, rules, settings)
    assert first["posterior_distribution"] == third["posterior_distribution"]
    assert len(third["event_adjustments"]) == 2


def test_event_cap_and_disputed_proposals(tmp_path):
    state = demo_run(tmp_path)
    state.hypotheses[0].direction = "positive"
    state.hypotheses[1].direction = "positive"
    settings = load_settings().model_copy(update={"max_total_log_shift": 0.01})
    belief = update_belief(state, load_rules(), settings)
    assert belief["total_log_shift"] == 0.01
    assert all("proposal" not in a["event"].lower() for a in belief["event_adjustments"])
    assert belief["calibrated"] is False


def test_budget_counts_search_retries_and_reserves_before_call():
    settings = load_settings().model_copy(update={"search_retries": 2, "max_search_calls": 1})
    secrets = Secrets(_env_file=None, tavily_api_key="test")
    budget = Budget(settings, secrets, Usage())
    calls = []
    client = TavilySearch(
        secrets, settings, budget, httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(503))
    )
    with pytest.raises(BudgetExceeded):
        client.search("test")
    assert len(calls) == budget.usage.search_calls == 1


def test_interruption_mid_search_preserves_round_and_queries(tmp_path):
    class InterruptedSearch(DemoSearch):
        def search(self, query):
            if self.calls == 1:
                raise RuntimeError("interrupted during query")
            return super().search(query)

    store = Store(tmp_path / "search.db")
    c = Controller(store, reports=tmp_path / "reports", search=InterruptedSearch())
    state = c.create_state("demo")
    with pytest.raises(RuntimeError, match="interrupted"):
        c.run(state)
    recovered = store.resume(state.run_id)
    assert recovered.iteration_count == 1 and len(recovered.current_round_queries) == 2
    finished = Controller(store, reports=tmp_path / "reports").run(recovered)
    assert finished.iteration_count == 2
    first_round = [r for r in finished.search_history if r["iteration"] == 1]
    assert len(first_round) == 3
    assert len({r["query"] for r in first_round}) == 3


def test_unresolved_scoring_and_comparison_modes(tmp_path):
    state = demo_run(tmp_path)
    with pytest.raises(ValueError, match="UNRESOLVED"):
        score(state.forecast, {"status": "UNRESOLVED"})
    same = compare_forecasts(state.forecast, state.forecast)
    assert all(p["delta"] == 0 for p in same["probability_changes"])
    with pytest.raises(ValueError, match="data mode"):
        compare_forecasts(state.forecast, state.forecast.model_copy(update={"mode": "live"}))


def test_as_of_and_dst(tmp_path):
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo(load_rules().timezone)
    assert datetime(2026, 7, 1, 13, tzinfo=eastern).astimezone(UTC).hour == 17
    assert datetime(2026, 12, 31, 13, tzinfo=eastern).astimezone(UTC).hour == 18
    c = Controller(Store(tmp_path / "x.db"))
    with pytest.raises(ValueError, match="current cutoff"):
        c.create_state("live", datetime(2025, 1, 1, tzinfo=UTC))
