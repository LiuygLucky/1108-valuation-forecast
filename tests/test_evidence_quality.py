from datetime import UTC, datetime

import pytest

from forecast_agent.belief import update_belief
from forecast_agent.config import load_rules, load_settings
from forecast_agent.controller import Controller
from forecast_agent.demo import DemoLLM, DemoSearch
from forecast_agent.evidence import process_evidence, retrieval_verified
from forecast_agent.report import make_forecast
from forecast_agent.research import critique
from forecast_agent.schemas import CognitiveState, Critique, EvidenceBatch, EvidenceReview, Source
from forecast_agent.storage import Store, digest


def test_live_source_requires_real_trace_and_intact_content(tmp_path):
    state = Controller(Store(tmp_path / "live.db")).create_state("live")
    now = datetime.now(UTC)
    content = "An original public statement"
    url = "https://openai.com/example"
    source = Source(
        source_id="src_" + digest(url + content)[:24],
        title="Statement",
        url=url,
        source="openai.com",
        published_at=now,
        retrieved_at=now,
        content=content,
        query="original query",
        content_hash=digest(content),
    )
    assert not retrieval_verified(source, state)
    state.search_history = [{"status": "success", "query": source.query, "source_ids": [source.source_id]}]
    assert retrieval_verified(source, state)
    source.content = "tampered text"
    assert not retrieval_verified(source, state)


def test_partial_support_is_research_only(tmp_path):
    controller = Controller(Store(tmp_path / "demo.db"), reports=tmp_path / "reports")
    state = controller.run(controller.create_state("demo"))
    evidence_id = state.critique.accepted_evidence[0]

    class PartialReview(DemoLLM):
        def generate(self, task, payload, schema):
            result = super().generate(task, payload, schema)
            if schema is Critique:
                next_review = next(r for r in result.evidence_reviews if r.evidence_id == evidence_id)
                next_review.support_level = "partial"
            return result

    state.critique = critique(PartialReview(), state)
    partial = next(e for e in state.evidence if e.evidence_id == evidence_id)
    assert evidence_id in state.critique.accepted_evidence
    assert partial.support_level == "partial"
    state.belief_state = update_belief(state, load_rules(), load_settings())
    assert evidence_id not in make_forecast(state, load_rules(), load_settings()).key_evidence_ids
    assert all(evidence_id not in a["evidence_ids"] for a in state.belief_state["event_adjustments"])


def test_only_partial_accepted_evidence_keeps_baseline_with_warning(tmp_path):
    controller = Controller(Store(tmp_path / "partial.db"), reports=tmp_path / "reports")
    state = controller.run(controller.create_state("demo"))
    for ev in state.evidence:
        if ev.evidence_id in state.critique.accepted_evidence:
            ev.support_level = "partial"
    controller.UpdateBelief(state)
    assert not state.belief_state["event_adjustments"]
    assert any("without event adjustments" in warning for warning in state.warnings)


def test_missing_or_non_direct_reviews_cannot_support_forecast(tmp_path):
    controller = Controller(Store(tmp_path / "review.db"), reports=tmp_path / "reports")
    state = controller.run(controller.create_state("demo"))

    class MissingReview(DemoLLM):
        def generate(self, task, payload, schema):
            result = super().generate(task, payload, schema)
            if schema is Critique:
                result.evidence_reviews = []
            return result

    state.critique = critique(MissingReview(), state)
    assert not state.critique.accepted_evidence
    with pytest.raises(ValueError, match="accepted no evidence"):
        controller.UpdateBelief(state)


def test_out_of_scope_critic_ids_are_recorded_and_excluded(tmp_path):
    controller = Controller(Store(tmp_path / "unknown.db"), reports=tmp_path / "reports")
    state = controller.run(controller.create_state("demo"))

    class OutOfScopeReview(DemoLLM):
        def generate(self, task, payload, schema):
            result = super().generate(task, payload, schema)
            if schema is Critique:
                result.accepted_evidence.append("ev_not_in_review")
                result.evidence_reviews.append(
                    EvidenceReview(
                        evidence_id="ev_not_in_review",
                        support_level="direct",
                        first_hand=True,
                        rationale="model hallucination",
                    )
                )
            return result

    reviewed = critique(OutOfScopeReview(), state)
    assert "ev_not_in_review" not in reviewed.accepted_evidence
    assert all(r.evidence_id != "ev_not_in_review" for r in reviewed.evidence_reviews)
    assert any("out-of-scope" in warning for warning in reviewed.potential_biases)


def test_source_type_and_reliability_are_deterministic(tmp_path):
    from forecast_agent.evidence import source_quality, source_type

    state = Controller(Store(tmp_path / "types.db")).create_state("live")
    source = Source(
        source_id="src_test",
        title="Company announcement",
        url="https://openai.com/news/example",
        source="openai.com",
        retrieved_at=datetime.now(UTC),
        content="Example announcement",
        query="test",
        content_hash=digest("Example announcement"),
    )
    assert source_type(source, state) == "official"
    assert source_quality(source) == ("official", 0.95)
    source.url = "https://unlisted.example/news/example"
    assert source_type(source, state) == "other"
    assert source_quality(source) == ("unknown", 0.4)


def test_cross_source_candidate_requires_distinct_origin_and_quote():
    sources = DemoSearch().search("test")
    first = sources[0]
    second_content = "SYNTHETIC: A separate document confirms the enterprise subscription increase."
    second = Source(
        source_id="src_demo_second",
        title="DEMO / SYNTHETIC second origin",
        url="https://second.other.invalid/story",
        source="second.other.invalid",
        published_at=first.published_at,
        retrieved_at=first.retrieved_at,
        content=second_content,
        query="test",
        content_hash=digest(second_content),
        synthetic=True,
    )
    first_ev = (
        DemoLLM().generate("extract", {"sources": [first.model_dump(mode="json")]}, EvidenceBatch).evidence[0]
    )
    second_ev = first_ev.model_copy(
        update={
            "evidence_id": "ev_demo_second",
            "source_ids": [second.source_id],
            "supporting_quote": second_content,
        }
    )
    state = CognitiveState(
        question="test", mode="demo", as_of="2026-11-07T18:00:00Z", target_date="2026-12-31"
    )
    state.sources = [first, second]
    state.evidence = process_evidence([first_ev, second_ev], state.sources, state, load_settings())
    state.retrieved_evidence_ids = [first_ev.evidence_id]

    class CrossReview(DemoLLM):
        def generate(self, task, payload, schema):
            result = super().generate(task, payload, schema)
            if schema is Critique:
                result.evidence_reviews = [
                    EvidenceReview(
                        evidence_id=first_ev.evidence_id,
                        support_level="direct",
                        first_hand=False,
                        corroboration_candidate_ids=[second.source_id],
                        rationale="Separate synthetic text and publisher",
                    ),
                ]
                if any(e["evidence_id"] == second_ev.evidence_id for e in payload["evidence"]):
                    result.evidence_reviews.append(
                        EvidenceReview(
                            evidence_id=second_ev.evidence_id,
                            support_level="direct",
                            first_hand=False,
                            rationale="Separate synthetic text directly states the same claim",
                        )
                    )
                result.accepted_evidence = [first_ev.evidence_id]
            return result

    critique(CrossReview(), state)
    assert state.evidence[0].corroboration_candidate_ids == [second.source_id]
    second.url = "https://second.example.invalid/story"
    second.source = "second.example.invalid"
    critique(CrossReview(), state)
    assert not state.evidence[0].corroboration_candidate_ids
    second.url = "https://second.other.invalid/story"
    second.source = "second.other.invalid"
    second.content = first.content
    second.content_hash = first.content_hash
    state.evidence = process_evidence([first_ev, second_ev], state.sources, state, load_settings())
    critique(CrossReview(), state)
    assert not state.evidence[0].corroboration_candidate_ids
