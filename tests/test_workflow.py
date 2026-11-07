from datetime import timedelta

import pytest

from forecast_agent.config import Secrets, load_rules, load_settings
from forecast_agent.controller import Controller
from forecast_agent.demo import DEMO_AS_OF, DemoLLM, DemoSearch
from forecast_agent.evidence import process_evidence, source_exclusions, unique_sources
from forecast_agent.schemas import CognitiveState, EvidenceBatch
from forecast_agent.storage import Store


def synthetic_evidence():
    sources = DemoSearch().search("test")
    batch = DemoLLM().generate(
        "extract", {"sources": [s.model_dump(mode="json") for s in sources]}, EvidenceBatch
    )
    state = CognitiveState(question="test", mode="demo", as_of=DEMO_AS_OF, target_date="2026-12-31")
    return state, sources, batch.evidence


def test_time_and_quote_filtering():
    state, sources, items = synthetic_evidence()
    sources[0].published_at = DEMO_AS_OF + timedelta(days=1)
    items[1].supporting_quote = "Invented unsupported claim"
    result = process_evidence(items, sources, state, load_settings())
    assert "published after as_of" in result[0].exclusion_reasons
    assert not result[1].supported
    state.as_of -= timedelta(days=10)
    assert all(e.exclusion_reasons for e in process_evidence(items, sources, state, load_settings()))


def test_retrieval_after_historical_cutoff_is_excluded():
    state, sources, _ = synthetic_evidence()
    state.mode = "historical"
    sources[0].synthetic = False
    sources[0].retrieved_at = DEMO_AS_OF + timedelta(seconds=1)
    assert "not available" in " ".join(source_exclusions(sources[0], state))


def test_live_retrieval_window_excludes_late_resume():
    state, sources, _ = synthetic_evidence()
    state.mode = "live"
    sources[0].synthetic = False
    sources[0].published_at = state.as_of - timedelta(days=1)
    state.started_at = state.as_of
    sources[0].retrieved_at = state.started_at + timedelta(minutes=20)
    assert not source_exclusions(sources[0], state)
    sources[0].retrieved_at = state.started_at + timedelta(minutes=31)
    assert "not available" in " ".join(source_exclusions(sources[0], state))


def test_expired_live_search_requires_new_run(tmp_path):
    controller = Controller(Store(tmp_path / "expired.db"))
    state = controller.create_state("live")
    state.started_at -= timedelta(minutes=31)
    with pytest.raises(ValueError, match="create a new run"):
        controller.Search(state)


def test_duplicate_syndications_have_one_weight():
    state, sources, items = synthetic_evidence()
    extra = sources[0].model_copy(update={"source_id": "syndicated", "url": "https://another.invalid/copy"})
    assert len(unique_sources(sources + [extra])) == len(sources)
    duplicate = items[0].model_copy(update={"evidence_id": "duplicate", "source_ids": [extra.source_id]})
    result = process_evidence(items + [duplicate], sources + [extra], state, load_settings())
    assert sum(not e.exclusion_reasons for e in result if e.category == "revenue") == 1


def test_relevant_excerpt_skips_navigation_without_mutating_source():
    from forecast_agent.evidence import safe_excerpt

    _, sources, _ = synthetic_evidence()
    raw = "* [Navigation](https://example.invalid)\n" * 150 + sources[0].content
    source = sources[0].model_copy(update={"content": raw})
    excerpt = safe_excerpt(source, max_chars=500)
    assert "subscriptions" in excerpt["content"]
    assert source.content == raw
    assert excerpt["excerpt_source_offsets"][0] > 500


def test_same_quote_with_inconsistent_category_is_still_a_duplicate():
    state, sources, items = synthetic_evidence()
    duplicate = items[0].model_copy(update={"evidence_id": "cross_category", "category": "other"})
    result = process_evidence([items[0], duplicate], sources, state, load_settings())
    assert sum(not e.exclusion_reasons for e in result) == 1


def test_distinct_same_day_events_are_not_merged():
    state, sources, items = synthetic_evidence()
    other = items[0].model_copy(
        update={
            "evidence_id": "other_event",
            "claim": "A different enterprise contract was signed on the same day",
            "supporting_quote": "A different enterprise contract",
        }
    )
    sources[0].content += " A different enterprise contract was signed on the same day."
    result = process_evidence([items[0], other], sources, state, load_settings())
    assert result[0].event_cluster != result[1].event_cluster
    assert not any("duplicate event" in reason for reason in result[1].exclusion_reasons)


def test_full_graph_round_limit_persistence_and_recovery(tmp_path):
    store = Store(tmp_path / "demo.sqlite3")
    settings = load_settings().model_copy(update={"max_iterations": 2})
    controller = Controller(
        store, settings=settings, reports=tmp_path / "reports", secrets=Secrets(_env_file=None)
    )
    result = controller.run(controller.create_state("demo"))
    assert result.status == "complete" and result.iteration_count == 2
    assert sum(p.probability for p in result.forecast.probabilities) == pytest.approx(1)
    assert len(result.forecast.probabilities) == 6
    assert len(store.history("demo")) == 1 and store.history("live") == []
    assert store.resume(result.run_id).forecast == result.forecast
    assert store.saved_state(result.run_id).sources == result.sources
    assert (tmp_path / "reports" / result.run_id / "report.md").is_file()
    assert "DEMO / SYNTHETIC" in result.report
    assert {"Reason", "Critique", "UpdateBelief", "SaveRun"} <= {
        r["node"] for r in store.trace(result.run_id)
    }
    assert controller.run(store.resume(result.run_id)).forecast == result.forecast
    from forecast_agent.report import markdown_report

    disputed = result.model_copy(deep=True)
    disputed_id = disputed.critique.accepted_evidence[0]
    disputed.critique.accepted_evidence.remove(disputed_id)
    disputed.critique.disputed_evidence.append(disputed_id)
    facts = markdown_report(disputed).split("## 当前关键事实 / 报道", 1)[1].split("## 正面因素", 1)[0]
    assert disputed_id not in facts
    with store.connect() as db, pytest.raises(Exception, match="immutable"):
        db.execute("DELETE FROM forecasts")


def test_real_mode_cannot_use_demo_anchor(tmp_path):
    from forecast_agent.demo import demo_anchor
    from forecast_agent.observations import select_anchor

    store = Store(tmp_path / "test.db")
    store.save_observation(demo_anchor(load_rules()))
    with pytest.raises(ValueError, match="No eligible NPM"):
        select_anchor(store, DEMO_AS_OF, load_rules(), load_settings())


def test_failed_node_resume_does_not_repeat_search(tmp_path):
    class InterruptedLLM(DemoLLM):
        def generate(self, task, payload, schema):
            from forecast_agent.schemas import Reasoning

            if schema is Reasoning:
                raise RuntimeError("simulated interruption")
            return super().generate(task, payload, schema)

    store = Store(tmp_path / "resume.db")
    first = Controller(store, reports=tmp_path / "reports", llm=InterruptedLLM())
    state = first.create_state("demo")
    with pytest.raises(RuntimeError, match="interruption"):
        first.run(state)
    saved = store.resume(state.run_id)
    assert saved.next_node == "Reason"
    searches_before = len(saved.search_history)
    second = Controller(store, reports=tmp_path / "reports")
    result = second.run(saved)
    assert result.status == "complete"
    assert len(result.search_history) >= searches_before
    assert sum(r["node"] == "PlanResearch" for r in store.trace(state.run_id)) == 1
