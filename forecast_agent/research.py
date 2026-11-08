"""Small cognitive modules sharing a validated structured LLM interface."""

from forecast_agent.clients import StructuredLLM
from forecast_agent.evidence import normalize, publisher_identity, safe_excerpt, unique_sources
from forecast_agent.schemas import CognitiveState, Critique, EvidenceBatch, Reasoning, ResearchPlan

MAX_REVIEW_EVIDENCE = 18
MAX_REVIEW_WITH_PEERS = 24


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
    evidence_by_id = {e.evidence_id: e for e in state.evidence}
    ranked = [evidence_by_id[eid] for eid in state.retrieved_evidence_ids if eid in evidence_by_id]
    selected, seen_categories = [], set()
    for ev in ranked:
        if ev.category not in seen_categories:
            selected.append(ev)
            seen_categories.add(ev.category)
    selected.extend(e for e in ranked if e not in selected)
    selected = selected[:MAX_REVIEW_EVIDENCE]
    selected_ids = {e.evidence_id for e in selected}
    clusters = {e.event_cluster for e in selected}
    peers = [
        e
        for e in state.evidence
        if e.evidence_id not in selected_ids
        and e.event_cluster in clusters
        and e.supported
        and e.retrieval_verified
        and e.exclusion_reasons
        and all(r.startswith("duplicate event:") for r in e.exclusion_reasons)
    ]
    reviewed = selected + peers[: max(0, MAX_REVIEW_WITH_PEERS - len(selected))]
    cited_sources = {sid for e in reviewed for sid in e.source_ids}
    result = llm.generate(
        "Independently challenge the research. Check contradictions, one-sided search, speculation treated as "
        "facts, syndicated duplicates, correlation/causality confusion, negative risks and missing variables. "
        "Return accepted/disputed evidence IDs from input only; absent support is not acceptance. "
        "Seek information available at as_of. The unknown future settlement itself is not a researchable gap. "
        "Only the separate verified NPM anchor can be a baseline; financing evidence cannot replace it. "
        "For every accepted evidence ID, review whether its exact quote directly supports the entire claim, "
        "partially supports it, is background only, or contradicts it. "
        "Support level measures QUOTE versus CLAIM entailment only. A quote directly stating a funding "
        "round is direct support for that funding claim, even though funding valuation is not NPM Valuation. "
        "Do not downgrade support because the source is secondary, the event is a forecast, or its future "
        "valuation impact is uncertain; assess those separately via source type, event status and biases. "
        "If the quote needs an unstated year, entity or amount to support the claim, mark partial. "
        "Mark first_hand only when the cited "
        "publisher directly observed or issued the specific claim. Suggest corroboration_candidate_ids only for "
        "separate original origins supporting the same claim; syndications and shared quotes are not independent. "
        "Give a brief rationale. Do not invent source IDs. A missing review cannot be accepted.",
        {
            "as_of": state.as_of.isoformat(),
            "target_date": state.target_date.isoformat(),
            "evidence": [
                {
                    "evidence_id": e.evidence_id,
                    "source_ids": e.source_ids,
                    "claim": e.claim,
                    "supporting_quote": e.supporting_quote,
                    "category": e.category,
                    "event_status": e.event_status,
                    "epistemic_status": e.epistemic_status,
                    "published_at": e.published_at.isoformat() if e.published_at else None,
                    "direction": e.direction,
                    "event_cluster": e.event_cluster,
                    "source_type": e.source_type,
                    "exclusion_reasons": e.exclusion_reasons,
                }
                for e in reviewed
            ],
            "sources": [
                {"source_id": s.source_id, "title": s.title, "url": s.url}
                for s in state.sources
                if s.source_id in cited_sources
            ],
            "hypotheses": [
                {
                    "event": h.event,
                    "direction": h.direction,
                    "evidence_ids": [eid for eid in h.evidence_ids if eid in selected_ids],
                    "mechanism": h.mechanism,
                    "counterarguments": h.counterarguments,
                }
                for h in state.hypotheses
                if set(h.evidence_ids) & selected_ids
            ],
        },
        Critique,
    )
    known = {e.evidence_id for e in reviewed}
    unknown = set(result.accepted_evidence + result.disputed_evidence) - known
    unknown.update(r.evidence_id for r in result.evidence_reviews if r.evidence_id not in known)
    if unknown:
        result.potential_biases.append(
            f"Critic supplied {len(unknown)} out-of-scope evidence IDs; excluded from review"
        )
    result.accepted_evidence = [eid for eid in result.accepted_evidence if eid in known]
    result.disputed_evidence = [eid for eid in result.disputed_evidence if eid in known]
    reviews = [r for r in result.evidence_reviews if r.evidence_id in known]
    duplicates = {r.evidence_id for r in reviews if sum(x.evidence_id == r.evidence_id for x in reviews) > 1}
    if duplicates:
        result.potential_biases.append(
            f"Critic supplied {len(duplicates)} duplicate evidence reviews; disputed"
        )
        result.disputed_evidence.extend(sorted(duplicates))
    result.evidence_reviews = [r for r in reviews if r.evidence_id not in duplicates]
    review_map = {r.evidence_id: r for r in result.evidence_reviews}
    source_map = {s.source_id: s for s in state.sources}
    for ev in reviewed:
        review = review_map.get(ev.evidence_id)
        if review is None:
            continue
        ev.support_level = review.support_level
        ev.first_hand = (
            review.first_hand
            and review.support_level == "direct"
            and ev.source_type in {"primary_data", "official", "established_reporting"}
        )
        independent = []
        for sid in review.corroboration_candidate_ids:
            other = source_map.get(sid)
            if other is None or sid in ev.source_ids:
                continue
            peers = [
                e
                for e in reviewed
                if sid in e.source_ids
                and e.event_cluster == ev.event_cluster
                and e.supported
                and e.retrieval_verified
                and (review_map.get(e.evidence_id) is not None)
                and review_map[e.evidence_id].support_level == "direct"
                and not [r for r in e.exclusion_reasons if not r.startswith("duplicate event:")]
            ]
            if not peers or any(
                publisher_identity(other) == publisher_identity(source_map[own])
                or other.content_hash == source_map[own].content_hash
                for own in ev.source_ids
                if own in source_map
            ):
                continue
            if all(normalize(peer.supporting_quote) == normalize(ev.supporting_quote) for peer in peers):
                continue
            independent.append(sid)
        ev.corroboration_candidate_ids = sorted(set(independent))
        base = {
            "primary_data": 38,
            "official": 36,
            "established_reporting": 30,
            "other": 12,
            "social": 5,
            "unreviewed": 0,
        }[ev.source_type]
        support = {"direct": 30, "partial": 10, "background": 0, "contradicts": 0}[review.support_level]
        ev.quality_score = min(
            100,
            base
            + support
            + 15 * ev.retrieval_verified
            + 10 * ev.first_hand
            + 9 * bool(ev.corroboration_candidate_ids),
        )
    excluded = {e.evidence_id for e in reviewed if e.exclusion_reasons or not e.supported}
    excluded.update(
        eid
        for eid in result.accepted_evidence
        if eid not in review_map or review_map[eid].support_level in {"background", "contradicts"}
    )
    conflicts = set()
    valuation_groups = {}
    for ev in reviewed:
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
    directions = {e.direction for e in reviewed if e.evidence_id in result.accepted_evidence}
    if "negative" not in directions:
        result.missing_information.append(
            "No accepted negative evidence: search costs, competition and regulation"
        )
        result.recommended_followup_queries.insert(0, "OpenAI costs competition regulatory risks Reuters")
    result.recommended_followup_queries = list(dict.fromkeys(result.recommended_followup_queries))[:6]
    return result
