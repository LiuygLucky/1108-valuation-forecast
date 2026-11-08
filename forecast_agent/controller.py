"""LangGraph orchestration with durable node checkpoints and explicit recovery."""

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph

from forecast_agent.belief import update_belief
from forecast_agent.clients import Budget, BudgetExceeded, CompatibleLLM, ProviderError, TavilySearch
from forecast_agent.config import ROOT, Secrets, Settings, load_rules, load_settings
from forecast_agent.demo import DEMO_AS_OF, DemoLLM, DemoSearch, demo_anchor
from forecast_agent.evidence import (
    LIVE_COLLECTION_WINDOW,
    deduplicate_evidence,
    process_evidence,
    source_exclusions,
)
from forecast_agent.memory import VectorMemory
from forecast_agent.observations import select_anchor
from forecast_agent.report import export_report, make_forecast, markdown_report
from forecast_agent.research import critique, extract_evidence, plan_research, reason
from forecast_agent.schemas import CognitiveState, MarketRules, uid, utcnow
from forecast_agent.storage import Store

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    state: CognitiveState


class Controller:
    def __init__(
        self,
        store: Store,
        settings: Settings | None = None,
        rules: MarketRules | None = None,
        secrets: Secrets | None = None,
        reports: Path | None = None,
        on_progress: Callable | None = None,
        search=None,
        llm=None,
    ):
        self.store = store
        self.settings, self.rules = settings or load_settings(), rules or load_rules()
        self.secrets = secrets or Secrets()
        self.reports = reports or ROOT / "reports"
        self.on_progress = on_progress
        self.search_override, self.llm_override = search, llm
        self.memory = VectorMemory(self.settings)

    def create_state(self, mode="live", as_of=None) -> CognitiveState:
        now = utcnow()
        cutoff = as_of or (DEMO_AS_OF if mode == "demo" else now)
        if mode == "live" and abs((now - cutoff).total_seconds()) > 60:
            raise ValueError("Live mode only accepts a current cutoff; use historical for archived research")
        if cutoff > now + timedelta(minutes=1):
            raise ValueError("Future information cutoff is invalid")
        return CognitiveState(
            question=self.rules.question,
            mode=mode,
            as_of=cutoff,
            target_date=self.rules.target_date,
            started_at=now,
            settings_snapshot=self.settings.model_dump(mode="json"),
            rules_snapshot=self.rules.model_dump(mode="json"),
            provider_snapshot={
                "llm_model": self.secrets.llm_model,
                "llm_base_url": self.secrets.llm_base_url,
            },
        )

    def run(self, state: CognitiveState) -> CognitiveState:
        if state.status == "complete":
            return state
        if state.status == "failed" and state.warnings and state.warnings[-1].endswith("BudgetExceeded"):
            reviewed = self.store.last_completed_review(state.run_id)
            if reviewed is None or not reviewed.critique or not reviewed.critique.accepted_evidence:
                raise BudgetExceeded(
                    "Budget exhausted before any complete accepted evidence review; forecast refused"
                )
            # Retain costs and all retrievals, but restore a coherent, previously reviewed evidence/hypothesis set.
            reviewed.usage = state.usage
            reviewed.search_history = state.search_history
            reviewed.sources = list({s.source_id: s for s in reviewed.sources + state.sources}.values())
            reviewed.review_iteration = reviewed.iteration_count
            reviewed.iteration_count = state.iteration_count
            reviewed.warnings = list(
                dict.fromkeys(
                    reviewed.warnings
                    + state.warnings
                    + [
                        f"Budget exhausted during follow-up; numerical forecast uses completed review from round "
                        f"{reviewed.review_iteration}. Later retrievals are archived but not used as new evidence."
                    ]
                )
            )
            reviewed.status, reviewed.next_node = "running", "UpdateBelief"
            state = reviewed
            self.store.checkpoint(state, "BudgetFallbackToCompletedReview")
        if state.settings_snapshot != self.settings.model_dump(
            mode="json"
        ) or state.rules_snapshot != self.rules.model_dump(mode="json"):
            raise ValueError("Resume must use the original settings and rule snapshots")
        if state.mode != "demo" and state.provider_snapshot != {
            "llm_model": self.secrets.llm_model,
            "llm_base_url": self.secrets.llm_base_url,
        }:
            raise ValueError("Resume must use the same LLM provider/model; create a new run to change it")
        budget_settings = self.settings
        budget_secrets = self.secrets
        if state.mode == "demo":
            budget_settings = self.settings.model_copy(update={"search_cost_usd": 0.0})
            budget_secrets = self.secrets.model_copy(
                update={"llm_input_usd_per_million": 0.0, "llm_output_usd_per_million": 0.0}
            )
        self.budget = Budget(budget_settings, budget_secrets, state.usage)
        self.budget.on_reserve = lambda: self.store.checkpoint(state, "BudgetReservation")
        state.status = "running"
        self.store.checkpoint(state, "StartOrResume")
        if state.mode == "demo":
            self.search, self.llm = DemoSearch(self.budget), DemoLLM(self.budget)
        else:
            self.llm = self.llm_override or CompatibleLLM(self.secrets, self.settings, self.budget)
            self.search = (
                None
                if state.mode == "historical"
                else (self.search_override or TavilySearch(self.secrets, self.settings, self.budget))
            )
        self.search = self.search_override or self.search
        self.llm = self.llm_override or self.llm
        return self.graph().invoke({"state": state}, {"recursion_limit": 80})["state"]

    def fork_completed_review(self, parent_run_id: str) -> CognitiveState:
        reviewed = self.store.last_completed_review(parent_run_id)
        if reviewed is None or reviewed.critique is None or not reviewed.critique.accepted_evidence:
            raise ValueError("No completed accepted evidence review to fork")
        return self._fork_checkpoint(reviewed, parent_run_id, "UpdateBelief")

    def fork_completed_reason(self, parent_run_id: str) -> CognitiveState:
        reasoned = self.store.last_completed_node(parent_run_id, "Reason")
        if reasoned is None or not reasoned.hypotheses:
            raise ValueError("No completed causal reasoning checkpoint to fork")
        return self._fork_checkpoint(reasoned, parent_run_id, "Critique")

    def _fork_checkpoint(self, parent: CognitiveState, parent_run_id: str, next_node: str) -> CognitiveState:
        fork = parent.model_copy(deep=True)
        fork.run_id = uid("run")
        fork.parent_run_id = parent_run_id
        fork.status, fork.next_node = "running", next_node
        fork.forecast, fork.report = None, ""
        fork.warnings.append(
            f"Reused completed {fork.mode} research and prior costs from {parent_run_id}; "
            f"restarted at {next_node} without new search"
        )
        self.store.checkpoint(fork, f"ForkTo{next_node}")
        return fork

    def graph(self):
        graph = StateGraph(GraphState)
        nodes = [
            "ParseQuestion",
            "PlanResearch",
            "Search",
            "ProcessEvidence",
            "RetrieveMemory",
            "Reason",
            "Critique",
            "CheckInformationSufficiency",
            "UpdateBelief",
            "GenerateForecast",
            "GenerateReport",
            "SaveRun",
        ]
        for i, name in enumerate(nodes):
            next_name = nodes[i + 1] if i + 1 < len(nodes) else "END"
            graph.add_node(name, self.wrap(name, next_name))
        graph.add_conditional_edges(START, lambda s: s["state"].next_node, {x: x for x in nodes})
        for i, name in enumerate(nodes[:-1]):
            if name == "CheckInformationSufficiency":
                graph.add_conditional_edges(
                    name, lambda s: s["state"].next_node, {"Search": "Search", "UpdateBelief": "UpdateBelief"}
                )
            else:
                graph.add_edge(name, nodes[i + 1])
        graph.add_edge("SaveRun", END)
        return graph.compile()

    def wrap(self, name, next_name):
        def execute(container):
            state = container["state"]
            state.next_node = name
            self.budget.usage = state.usage
            self.budget.on_reserve = lambda: self.store.checkpoint(state, "BudgetReservation")
            if self.on_progress:
                self.on_progress(name, state)
            try:
                getattr(self, name)(state)
                if name != "CheckInformationSufficiency":
                    state.next_node = next_name
                if name == "SaveRun":
                    state.status = "complete"
                CognitiveState.model_validate(state.model_dump())
                self.store.checkpoint(state, name)
                return {"state": state}
            except Exception as exc:
                state.status, state.next_node = "failed", name
                state.warnings.append(f"{name} failed: {type(exc).__name__}")
                self.store.checkpoint(state, name + ":failed")
                logger.error("Run %s failed at %s (%s)", state.run_id, name, type(exc).__name__)
                raise

        return execute

    def ParseQuestion(self, state: CognitiveState) -> None:
        if state.as_of.astimezone(ZoneInfo(self.rules.timezone)).date() > self.rules.target_date:
            raise ValueError("Forecast cutoff is after the fixed target date; use settlement commands")
        state.anchor = (
            demo_anchor(self.rules)
            if state.mode == "demo"
            else select_anchor(self.store, state.as_of, self.rules, self.settings)
        )
        if state.mode == "demo":
            state.warnings.append("DEMO / SYNTHETIC: all facts and NPM anchor are fictional test fixtures")
        if state.mode == "live":
            state.warnings.append(
                "Live search was retrieved after as_of; this run is not a historically isolated backtest"
            )
        if not state.usage.cost_complete:
            state.warnings.append(
                "LLM price unknown: dollar estimate excludes unknown LLM costs; token/call limits remain enforced"
            )

    def PlanResearch(self, state: CognitiveState) -> None:
        plan = plan_research(self.llm, state, self.settings.preferred_domains)
        state.research_plan = sorted(plan.items, key=lambda item: item.priority)
        # Round-robin across research questions avoids spending a whole round on one factor.
        state.pending_queries = list(
            dict.fromkeys(
                item.suggested_queries[i]
                for i in range(max(len(item.suggested_queries) for item in state.research_plan))
                for item in state.research_plan
                if i < len(item.suggested_queries)
            )
        )
        if state.mode == "live":
            state.pending_queries.insert(
                1,
                (
                    f"OpenAI computing costs cash burn competition regulatory risks Reuters Financial Times "
                    f"{state.as_of:%B %Y}"
                ),
            )

    def Search(self, state: CognitiveState) -> None:
        if state.mode == "live" and utcnow() > state.started_at + LIVE_COLLECTION_WINDOW:
            raise ValueError("Live collection window expired; create a new run with a current cutoff")
        if not state.search_round_active:
            if state.iteration_count >= self.settings.max_iterations:
                raise ValueError("Research iteration cap exceeded")
            state.iteration_count += 1
            state.round_token_start = state.usage.reserved_tokens
            state.search_round_active = True
            executed = {row.get("query") for row in state.search_history if row.get("status") == "success"}
            state.current_round_queries = [q for q in state.pending_queries if q not in executed][
                : self.settings.queries_per_round
            ]
            state.pending_queries = [q for q in state.pending_queries if q not in state.current_round_queries]
            self.store.checkpoint(state, "Search:round")
        if state.mode == "historical":
            state.sources = [s for s in self.store.sources(False) if not source_exclusions(s, state)]
            state.archived_source_ids = [s.source_id for s in state.sources]
            state.search_history.append({"mode": "archived only", "iteration": state.iteration_count})
            state.search_round_active = False
            state.current_round_queries = []
            return
        for query in list(state.current_round_queries):
            try:
                sources = self.search.search(query)
                for source in sources:
                    self.store.save_source(source)
                    if source.source_id not in {s.source_id for s in state.sources}:
                        state.sources.append(source)
                state.search_history.append(
                    {
                        "query": query,
                        "status": "success",
                        "results": len(sources),
                        "source_ids": [source.source_id for source in sources],
                        "iteration": state.iteration_count,
                        "at": utcnow().isoformat(),
                    }
                )
            except ProviderError as exc:
                state.search_history.append(
                    {
                        "query": query,
                        "status": "failed",
                        "error": str(exc),
                        "iteration": state.iteration_count,
                        "at": utcnow().isoformat(),
                    }
                )
                state.warnings.append(str(exc))
            state.current_round_queries.remove(query)
            self.store.checkpoint(state, "Search:query")
        state.search_round_active = False
        if not state.sources:
            raise ProviderError("No sources available after bounded search; real forecast refused")

    def ProcessEvidence(self, state: CognitiveState) -> None:
        known = {sid for e in state.evidence for sid in e.source_ids}
        batch = extract_evidence(self.llm, state.sources, known)
        processed = process_evidence(batch.evidence, state.sources, state, self.settings)
        for ev in processed:
            ev.evidence_id = self.store.save_evidence(ev)
            if ev.evidence_id not in {e.evidence_id for e in state.evidence}:
                state.evidence.append(ev)
        state.evidence = deduplicate_evidence(state.evidence)
        state.evidence_ids = [e.evidence_id for e in state.evidence]

    def RetrieveMemory(self, state: CognitiveState) -> None:
        source_map = {s.source_id: s for s in state.sources}
        archived = self.store.sources(state.mode == "demo")
        state.archived_source_ids = list(
            dict.fromkeys(state.archived_source_ids + [s.source_id for s in archived])
        )
        for source in archived:
            if not source_exclusions(source, state):
                source_map.setdefault(source.source_id, source)
        state.sources = list(source_map.values())
        local = [
            e
            for e in self.store.evidence(state.mode == "demo")
            if e.evidence_id not in state.evidence_ids and all(sid in source_map for sid in e.source_ids)
        ]
        local = process_evidence(local, state.sources, state, self.settings)
        # Retain excluded records in the audit; only eligible records enter vector retrieval.
        state.evidence = deduplicate_evidence(state.evidence + local)
        state.evidence_ids = [e.evidence_id for e in state.evidence]
        retrieved = self.memory.retrieve(state.question, state.evidence, self.settings.max_evidence)
        state.retrieved_evidence_ids = [e.evidence_id for e in retrieved]
        if not retrieved:
            raise ValueError("No temporally eligible, source-supported evidence; forecast refused")

    def Reason(self, state: CognitiveState) -> None:
        result = reason(self.llm, state)
        known = set(state.retrieved_evidence_ids)
        if any(not set(h.evidence_ids) <= known for h in result.hypotheses):
            raise ValueError("Reasoner cited unavailable evidence")
        state.hypotheses = result.hypotheses
        state.information_gaps = result.information_gaps
        state.causal_relations = [
            {"event": h.event, "path": h.mechanism, "evidence_ids": h.evidence_ids} for h in result.hypotheses
        ]

    def Critique(self, state: CognitiveState) -> None:
        state.critique = critique(self.llm, state)
        state.review_iteration = state.iteration_count
        state.information_gaps = list(
            dict.fromkeys(state.information_gaps + state.critique.missing_information)
        )

    def CheckInformationSufficiency(self, state: CognitiveState) -> None:
        queries = state.critique.recommended_followup_queries
        executed = {r.get("query") for r in state.search_history}
        state.pending_queries = list(
            dict.fromkeys(q for q in queries + state.pending_queries if q not in executed)
        )
        followup = (
            state.mode != "historical"
            and state.information_gaps
            and state.pending_queries
            and state.iteration_count < self.settings.max_iterations
            and state.usage.search_calls < self.settings.max_search_calls
            and state.usage.llm_calls + 3 <= self.settings.max_llm_calls
            and state.usage.reserved_tokens
            + max(
                (state.usage.reserved_tokens - state.round_token_start) * 1.25,
                3 * self.settings.max_output_tokens,
            )
            <= self.settings.max_tokens
        )
        state.next_node = "Search" if followup else "UpdateBelief"
        if state.information_gaps and not followup:
            state.warnings.append(
                "Research stopped at configured limits or no new queries; information gaps remain"
            )

    def UpdateBelief(self, state: CognitiveState) -> None:
        if not state.critique or not state.critique.accepted_evidence:
            raise ValueError("Independent critic accepted no evidence; forecast refused")
        if not any(
            e.evidence_id in state.critique.accepted_evidence and e.support_level == "direct"
            for e in state.evidence
        ):
            state.warnings.append(
                "No directly supported accepted event evidence; numerical forecast uses the NPM baseline "
                "and subjective scenarios without event adjustments"
            )
        state.belief_state = update_belief(state, self.rules, self.settings)

    def GenerateForecast(self, state: CognitiveState) -> None:
        state.forecast = make_forecast(state, self.rules, self.settings)

    def GenerateReport(self, state: CognitiveState) -> None:
        state.report = markdown_report(state)

    def SaveRun(self, state: CognitiveState) -> None:
        # Freeze final state before both SQLite and filesystem export, so recovery is idempotent.
        state.status, state.next_node = "complete", "END"
        self.store.save_forecast(state)
        # A previous crash may have committed SQLite before exporting all files.
        # Always export the immutable saved state, not recovery warnings added later.
        frozen = self.store.saved_state(state.run_id)
        export_report(frozen, self.reports)
        for field in type(state).model_fields:
            setattr(state, field, getattr(frozen, field))
