"""Explicit synthetic fixtures. Never used as fallback for a real API failure."""

from datetime import UTC, datetime

from forecast_agent.schemas import (
    Critique,
    Evidence,
    EvidenceBatch,
    Hypothesis,
    NPMObservation,
    Reasoning,
    ResearchItem,
    ResearchPlan,
    Source,
)
from forecast_agent.storage import digest

DEMO_AS_OF = datetime(2026, 11, 7, 18, tzinfo=UTC)


def demo_anchor(rules):
    return NPMObservation(
        valuation_trillion=1.05,
        source_url=rules.source_url,
        effective_date="2026-11-02",
        observed_at="2026-11-02T19:00:00Z",
        archive_path="SYNTHETIC_FIXTURE_NO_REAL_NPM_DATA",
        archive_sha256="SYNTHETIC",
        verified=True,
        synthetic=True,
        notes="DEMO / SYNTHETIC, not an actual OpenAI valuation",
    )


class DemoSearch:
    def __init__(self, budget=None):
        self.calls = 0
        self.budget = budget

    def search(self, query):
        if self.budget:
            self.budget.search()
        self.calls += 1
        rows = [
            (
                "revenue",
                "SYNTHETIC: Enterprise subscriptions increased in the fictional test quarter.",
                "2026-11-04T12:00:00Z",
            ),
            (
                "profitability",
                "SYNTHETIC: Computing expenses increased in the fictional test quarter.",
                "2026-11-05T12:00:00Z",
            ),
            (
                "financing",
                "SYNTHETIC: A funding proposal remains unconfirmed in this fictional scenario.",
                "2026-11-06T12:00:00Z",
            ),
        ]
        return [
            Source(
                source_id="src_demo_" + category,
                title="DEMO / SYNTHETIC " + category,
                url=f"https://{category}.example.invalid/synthetic",
                source=f"{category}.example.invalid",
                published_at=published,
                retrieved_at="2026-11-07T17:00:00Z",
                content=content,
                query=query,
                content_hash=digest(content),
                synthetic=True,
                date_provenance="synthetic fixture",
            )
            for category, content, published in rows
        ]


class DemoLLM:
    def __init__(self, budget=None):
        self.budget = budget

    def generate(self, task, payload, schema):
        if self.budget:
            self.budget.llm(0)
        if schema is ResearchPlan:
            result = ResearchPlan(
                items=[
                    ResearchItem(
                        research_question=f"DEMO: research {factor}",
                        rationale="SYNTHETIC workflow test",
                        priority=i + 1,
                        suggested_queries=[f"DEMO SYNTHETIC OpenAI {factor}"],
                        expected_information="SYNTHETIC supported evidence",
                    )
                    for i, factor in enumerate(["revenue", "costs", "funding"])
                ]
            )
        elif schema is EvidenceBatch:
            records = []
            for source in payload["sources"]:
                category = source["source_id"].removeprefix("src_demo_")
                records.append(
                    Evidence(
                        evidence_id="ev_demo_" + category,
                        source_ids=[source["source_id"]],
                        claim=source["content"],
                        category=category,
                        claim_type=category,
                        event_status="proposed" if category == "financing" else "completed",
                        epistemic_status="Reported Claim",
                        published_at=source["published_at"],
                        event_at=source["published_at"],
                        effective_at=source["published_at"],
                        supporting_quote=source["content"],
                        quote_location="synthetic fixture sentence 1",
                        supported=True,
                        direction="positive"
                        if category == "revenue"
                        else "negative"
                        if category == "profitability"
                        else "uncertain",
                        causal_mechanisms=[category],
                        uncertainty_notes=["SYNTHETIC, not factual evidence"],
                        scenario_tags=["SYNTHETIC"],
                        event_cluster="demo_" + category,
                        synthetic=True,
                    )
                )
            result = EvidenceBatch(evidence=records)
        elif schema is Reasoning:
            result = Reasoning(
                hypotheses=[
                    Hypothesis(
                        event=e["claim"],
                        mechanism=[e["category"], "future cash-flow expectations", "terminal NPM valuation"],
                        intermediate_variables=["revenue expectations", "cost expectations"],
                        direction=e["direction"],
                        counterarguments=[
                            "The effect may already be priced in; competing cost/revenue effects are unknown."
                        ],
                        evidence_ids=[e["evidence_id"]],
                        uncertainties=["SYNTHETIC; magnitude not empirically calibrated"],
                        priced_in="partial",
                        change_triggers=["Verified NPM change", "Confirmed operating results"],
                    )
                    for e in payload["evidence"]
                ],
                information_gaps=["Audited profitability is unavailable in this fixture"],
            )
        elif schema is Critique:
            result = Critique(
                accepted_evidence=[
                    e["evidence_id"] for e in payload["evidence"] if e["event_status"] == "completed"
                ],
                disputed_evidence=[
                    e["evidence_id"] for e in payload["evidence"] if e["event_status"] != "completed"
                ],
                missing_information=["Audited profitability; proposal completion"],
                potential_biases=["Synthetic evidence cannot validate real forecast quality"],
                recommended_followup_queries=["DEMO SYNTHETIC audited profitability counterevidence"],
            )
        else:
            raise ValueError("Unsupported synthetic schema")
        return schema.model_validate(result.model_dump())
