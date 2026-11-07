"""Small cognitive modules sharing a validated structured LLM interface."""

from forecast_agent.clients import StructuredLLM
from forecast_agent.evidence import safe_excerpt, unique_sources
from forecast_agent.schemas import CognitiveState, Critique, EvidenceBatch, Reasoning, ResearchPlan


def plan_research(llm: StructuredLLM, state: CognitiveState, preferred_domains: list[str]) -> ResearchPlan:
    return llm.generate(
        "Plan balanced research covering NPM anchor, completed versus proposed funding, revenue and costs, "
        "competition, regulation and macro. Include counterevidence. Source preference is not truth. "
        "Priority 1 is highest and 5 lowest. NPM means Nasdaq Private Market, never net profit margin.",
        {
            "question": state.question,
            "as_of": state.as_of.isoformat(),
            "preferred_domains": preferred_domains,
        },
        ResearchPlan,
    )


def extract_evidence(llm: StructuredLLM, sources, known_ids: set[str]) -> EvidenceBatch:
    fresh = [s for s in unique_sources(sources) if s.source_id not in known_ids]
    if not fresh:
        return EvidenceBatch(evidence=[])
    return llm.generate(
        "Extract only claims supported by exact quotes of at most 25 words from supplied sources. "
        "Use only supplied source_ids. Distinguish proposals/rumors from completed facts. "
        "Never turn financing valuation into NPM Valuation. Leave unknown dates null. "
        "Use at most one or two distinct key claims per source. All synthetic flags must match input.",
        {"sources": [safe_excerpt(s) for s in fresh[:12]]},
        EvidenceBatch,
    )


def reason(llm: StructuredLLM, state: CognitiveState) -> Reasoning:
    return llm.generate(
        "For each important event explain fact support, uncertain facts, intermediate variables, mechanism, "
        "valuation direction, priced-in status, opposing explanations and change triggers. "
        "Use only supplied evidence IDs. Unknown priced-in status must stay unknown; do not assume no. "
        "These are causal hypotheses, never identified causal effects. Find researchable information gaps "
        "as of the supplied cutoff, not future settlement data that cannot yet exist.",
        {
            "as_of": state.as_of.isoformat(),
            "target_date": state.target_date.isoformat(),
            "evidence": [
                e.model_dump(mode="json")
                for e in state.evidence
                if e.evidence_id in state.retrieved_evidence_ids
            ],
            "anchor": state.anchor.model_dump(mode="json") if state.anchor else None,
        },
        Reasoning,
    )


def critique(llm: StructuredLLM, state: CognitiveState) -> Critique:
    result = llm.generate(
        "Independently challenge the research. Check contradictions, one-sided search, speculation treated as "
        "facts, syndicated duplicates, correlation/causality confusion, negative risks and missing variables. "
        "Return accepted/disputed evidence IDs from input only; absent support is not acceptance. "
        "Seek information available at as_of. The unknown future settlement itself is not a researchable gap. "
        "Only the separate verified NPM anchor can be a baseline; financing evidence cannot replace it.",
        {
            "as_of": state.as_of.isoformat(),
            "target_date": state.target_date.isoformat(),
            "evidence": [e.model_dump(mode="json") for e in state.evidence],
            "hypotheses": [h.model_dump(mode="json") for h in state.hypotheses],
        },
        Critique,
    )
    known = {e.evidence_id for e in state.evidence}
    if not set(result.accepted_evidence + result.disputed_evidence) <= known:
        raise ValueError("Critic cited an unknown evidence ID")
    excluded = {e.evidence_id for e in state.evidence if e.exclusion_reasons or not e.supported}
    conflicts = set()
    valuation_groups = {}
    for ev in state.evidence:
        if ev.supported and ev.reported_valuation_trillion is not None:
            key = (ev.event_cluster, ev.claim_type, ev.valuation_basis)
            valuation_groups.setdefault(key, []).append(ev)
    for group in valuation_groups.values():
        if len({ev.reported_valuation_trillion for ev in group}) > 1:
            conflicts.update(ev.evidence_id for ev in group)
    if conflicts:
        result.potential_biases.append("Conflicting valuation claims within the same event cluster")
        result.missing_information.append("Reconcile conflicting amounts against original disclosures")
    result.disputed_evidence = sorted(set(result.disputed_evidence) | excluded | conflicts)
    result.accepted_evidence = sorted(set(result.accepted_evidence) - set(result.disputed_evidence))
    directions = {e.direction for e in state.evidence if e.evidence_id in result.accepted_evidence}
    if "negative" not in directions:
        result.missing_information.append(
            "No accepted negative evidence: search costs, competition and regulation"
        )
        result.recommended_followup_queries.insert(0, "OpenAI costs competition regulatory risks Reuters")
    result.recommended_followup_queries = list(dict.fromkeys(result.recommended_followup_queries))[:6]
    return result
