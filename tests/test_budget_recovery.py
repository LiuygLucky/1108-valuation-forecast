import pytest

from forecast_agent.clients import BudgetExceeded
from forecast_agent.controller import Controller
from forecast_agent.demo import DemoLLM
from forecast_agent.schemas import Reasoning
from forecast_agent.storage import Store


def test_exhausted_followup_recovers_last_review_without_new_llm_calls(tmp_path):
    class ExhaustedFollowup(DemoLLM):
        reasoning_calls = 0

        def generate(self, task, payload, schema):
            if schema is Reasoning:
                self.reasoning_calls += 1
                if self.reasoning_calls == 2:
                    raise BudgetExceeded("Synthetic follow-up budget exhausted")
            return super().generate(task, payload, schema)

    store = Store(tmp_path / "budget.db")
    c = Controller(store, reports=tmp_path / "reports", llm=ExhaustedFollowup())
    state = c.create_state("demo")
    with pytest.raises(BudgetExceeded):
        c.run(state)
    reviewed = store.last_completed_review(state.run_id)
    assert reviewed.iteration_count == 1
    failed = store.resume(state.run_id)
    usage_before = failed.usage.model_dump()
    recovered = c.run(failed)
    assert recovered.status == "complete" and recovered.review_iteration == 1
    assert recovered.iteration_count == 2
    assert recovered.usage.model_dump() == usage_before
    assert recovered.hypotheses == reviewed.hypotheses
    assert recovered.critique == reviewed.critique
    assert "Budget exhausted during follow-up" in recovered.report
    assert "BudgetFallbackToCompletedReview" in [r["node"] for r in store.trace(state.run_id)]
