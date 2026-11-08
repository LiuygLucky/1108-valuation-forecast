"""Validated boundaries shared by tools, storage, reasoning and numerical code."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def utc_dates(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Timestamp must include timezone")
            return value.astimezone(UTC)
        return value


Mode = Literal["live", "historical", "demo"]
Direction = Literal["positive", "negative", "uncertain"]


class Interval(Model):
    label: str
    lower: float = Field(ge=0)
    upper: float | None = None
    lower_closed: bool
    upper_closed: bool

    def contains(self, x: float) -> bool:
        return (x >= self.lower if self.lower_closed else x > self.lower) and (
            self.upper is None or (x <= self.upper if self.upper_closed else x < self.upper)
        )


class MarketRules(Model):
    question: str
    target_date: date
    valuation_metric: str
    unit: Literal["USD trillion"]
    source_url: str
    timezone: Literal["America/New_York"]
    update_hour: int = Field(ge=0, le=23)
    forecast_type: Literal["terminal_interval"]
    intervals: list[Interval]

    @model_validator(mode="after")
    def partition(self):
        if len(self.intervals) != 6:
            raise ValueError("The fixed task requires six intervals")
        first, last = self.intervals[0], self.intervals[-1]
        if first.lower != 0 or first.lower_closed or last.upper is not None or last.upper_closed:
            raise ValueError("Intervals must partition (0, infinity)")
        for i, part in enumerate(self.intervals):
            if part.upper is not None and part.upper <= part.lower:
                raise ValueError("Empty interval")
            if i:
                prev = self.intervals[i - 1]
                if prev.upper != part.lower or prev.upper_closed == part.lower_closed:
                    raise ValueError("Interval gap or overlap")
        return self


class Source(Model):
    source_id: str
    title: str
    url: str
    source: str
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    content: str
    query: str
    content_hash: str
    synthetic: bool = False
    date_provenance: str = "unknown"


class Evidence(Model):
    evidence_id: str = Field(default_factory=lambda: uid("ev"))
    source_ids: list[str] = Field(min_length=1)
    entity: str = "OpenAI"
    claim: str
    category: Literal[
        "valuation",
        "financing",
        "revenue",
        "profitability",
        "competition",
        "technology",
        "regulation",
        "macro",
        "other",
    ]
    claim_type: str
    event_status: Literal["completed", "proposed", "rumor", "forecast", "commentary", "unknown"]
    epistemic_status: Literal["Verified Fact", "Reported Claim", "Model Inference", "Assumption", "Unknown"]
    event_at: AwareDatetime | None = None
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime | None = None
    effective_at: AwareDatetime | None = None
    valuation_basis: str | None = None
    reported_valuation_trillion: float | None = Field(default=None, gt=0)
    supporting_quote: str = Field(min_length=1)
    quote_location: str
    supported: bool
    causal_mechanisms: list[str] = Field(default_factory=list)
    direction: Direction
    uncertainty_notes: list[str] = Field(default_factory=list)
    scenario_tags: list[str] = Field(default_factory=list)
    source_kind: Literal["official", "reporting", "analysis", "social", "unknown"] = "unknown"
    credibility: float = Field(default=0.3, ge=0, le=1)
    source_type: Literal[
        "primary_data", "official", "established_reporting", "other", "social", "unreviewed"
    ] = "unreviewed"
    source_reliability: Literal["high", "medium", "low", "unreviewed"] = "unreviewed"
    support_level: Literal["direct", "partial", "background", "contradicts", "unreviewed"] = "unreviewed"
    first_hand: bool = False
    retrieval_verified: bool = False
    corroboration_candidate_ids: list[str] = Field(default_factory=list)
    quality_score: int = Field(default=0, ge=0, le=100)
    event_cluster: str = ""
    stale: bool = False
    exclusion_reasons: list[str] = Field(default_factory=list)
    synthetic: bool = False

    @field_validator("supporting_quote")
    @classmethod
    def short_quote(cls, value):
        if len(value.split()) > 25 or len(value) > 300:
            raise ValueError("Supporting quote exceeds 25 words / 300 characters")
        return value


class EvidenceBatch(Model):
    evidence: list[Evidence] = Field(max_length=40)


class ResearchItem(Model):
    research_question: str
    rationale: str
    priority: int = Field(ge=1, le=5)
    suggested_queries: list[str] = Field(min_length=1, max_length=3)
    expected_information: str


class ResearchPlan(Model):
    items: list[ResearchItem] = Field(min_length=1, max_length=8)


class Hypothesis(Model):
    event: str
    mechanism: list[str] = Field(min_length=2)
    intermediate_variables: list[str]
    direction: Direction
    counterarguments: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1)
    priced_in: Literal["yes", "partial", "no", "unknown"]
    change_triggers: list[str]


class Reasoning(Model):
    hypotheses: list[Hypothesis] = Field(max_length=20)
    information_gaps: list[str]


class EvidenceReview(Model):
    evidence_id: str
    support_level: Literal["direct", "partial", "background", "contradicts"] = Field(
        description="How directly the quoted text entails this specific claim, not how directly it affects NPM valuation"
    )
    first_hand: bool
    corroboration_candidate_ids: list[str] = Field(default_factory=list)
    rationale: str


class Critique(Model):
    accepted_evidence: list[str]
    disputed_evidence: list[str]
    missing_information: list[str]
    potential_biases: list[str]
    recommended_followup_queries: list[str] = Field(max_length=6)
    evidence_reviews: list[EvidenceReview] = Field(default_factory=list)


class NPMObservation(Model):
    observation_id: str = Field(default_factory=lambda: uid("npm"))
    valuation_trillion: float = Field(gt=0)
    metric: Literal["Nasdaq Private Market OpenAI Valuation"] = "Nasdaq Private Market OpenAI Valuation"
    source_url: str
    effective_date: date
    observed_at: AwareDatetime
    archive_path: str
    archive_sha256: str
    verified: bool
    synthetic: bool = False
    notes: str = ""


class Probability(Model):
    interval: str
    probability: float = Field(ge=0, le=1)


class Forecast(Model):
    run_id: str
    question: str
    as_of: AwareDatetime
    target_date: date
    generated_at: AwareDatetime = Field(default_factory=utcnow)
    valuation_metric: str
    market_rules_source: str
    forecast_type: Literal["terminal_interval"] = "terminal_interval"
    model_version: str
    mode: Mode
    unit: Literal["USD trillion"] = "USD trillion"
    probabilities: list[Probability]
    baseline_probabilities: list[Probability]
    median_valuation: float = Field(gt=0)
    confidence_interval_90: tuple[float, float]
    key_evidence_ids: list[str]
    main_assumptions: list[str]
    limitations: list[str]
    belief_state: dict
    rules_snapshot: dict
    settings_snapshot: dict

    @model_validator(mode="after")
    def valid_distribution(self):
        rules = MarketRules.model_validate(self.rules_snapshot)
        for values in (self.probabilities, self.baseline_probabilities):
            if [x.interval for x in values] != [x.label for x in rules.intervals]:
                raise ValueError("Forecast intervals must match rule snapshot")
            if not math.isclose(sum(x.probability for x in values), 1.0, abs_tol=1e-9):
                raise ValueError("Probability sum must be 1")
        if not 0 < self.confidence_interval_90[0] <= self.median_valuation <= self.confidence_interval_90[1]:
            raise ValueError("Invalid valuation quantiles")
        return self


class Usage(Model):
    search_calls: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reserved_tokens: int = 0
    estimated_cost_usd: float = 0
    cost_complete: bool = False


class CognitiveState(Model):
    run_id: str = Field(default_factory=lambda: uid("run"))
    parent_run_id: str | None = None
    question: str
    mode: Mode
    as_of: AwareDatetime
    started_at: AwareDatetime = Field(default_factory=utcnow)
    target_date: date
    research_plan: list[ResearchItem] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    archived_source_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    retrieved_evidence_ids: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    causal_relations: list[dict] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    search_history: list[dict] = Field(default_factory=list)
    pending_queries: list[str] = Field(default_factory=list)
    current_round_queries: list[str] = Field(default_factory=list)
    search_round_active: bool = False
    round_token_start: int = 0
    review_iteration: int = 0
    critique: Critique | None = None
    belief_state: dict = Field(default_factory=dict)
    forecast: Forecast | None = None
    iteration_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    anchor: NPMObservation | None = None
    report: str = ""
    next_node: str = "ParseQuestion"
    status: Literal["running", "failed", "complete"] = "running"
    settings_snapshot: dict = Field(default_factory=dict)
    rules_snapshot: dict = Field(default_factory=dict)
    provider_snapshot: dict = Field(default_factory=dict)
