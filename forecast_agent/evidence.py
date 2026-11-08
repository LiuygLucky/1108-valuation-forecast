"""Deterministic provenance/time checks after untrusted model extraction."""

import re
from datetime import timedelta
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from forecast_agent.config import Settings
from forecast_agent.schemas import CognitiveState, Evidence, Source
from forecast_agent.storage import digest

LIVE_COLLECTION_WINDOW = timedelta(minutes=30)


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith("utm_") and k not in {"ref", "source"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(sorted(query)), ""))


def unique_sources(sources: list[Source]) -> list[Source]:
    seen_hash, seen_url, result = set(), set(), []
    for s in sorted(sources, key=lambda x: x.retrieved_at):
        key = canonical_url(s.url)
        if s.content_hash in seen_hash or key in seen_url:
            continue
        seen_hash.add(s.content_hash)
        seen_url.add(key)
        result.append(s)
    return result


def source_exclusions(source: Source, state: CognitiveState) -> list[str]:
    reasons = []
    if source.synthetic != (state.mode == "demo"):
        reasons.append("synthetic/live mode mismatch")
    if source.published_at is None:
        reasons.append("unknown publication time")
    elif source.published_at > state.as_of:
        reasons.append("published after as_of")
    if source.retrieved_at > state.as_of:
        # A live run may collect shortly after its frozen cutoff, including after a resume.
        # Later retrievals belong to a new forecast with a new information cutoff.
        if (
            state.mode != "live"
            or source.retrieved_at < state.started_at
            or source.retrieved_at > state.started_at + LIVE_COLLECTION_WINDOW
        ):
            reasons.append("not available in the archived information set at as_of")
    return reasons


def source_quality(source: Source) -> tuple[str, float]:
    host = (urlsplit(source.url).hostname or "").removeprefix("www.").lower()

    def match(domain):
        return host == domain or host.endswith("." + domain)

    if any(match(x) for x in ["openai.com", "nasdaqprivatemarket.com", "secondmarket.com"]):
        return "official", 0.95
    if any(match(x) for x in ["reuters.com", "bloomberg.com", "ft.com"]):
        return "reporting", 0.85
    if any(match(x) for x in ["x.com", "twitter.com", "reddit.com"]):
        return "social", 0.2
    if source.synthetic:
        return "unknown", 0.6
    return "unknown", 0.4


def source_type(source: Source, state: CognitiveState) -> str:
    host = (urlsplit(source.url).hostname or "").removeprefix("www.").lower()
    if canonical_url(source.url) == canonical_url(state.rules_snapshot.get("source_url", "")):
        return "primary_data"
    if host == "openai.com" or host.endswith(".openai.com"):
        return "official"
    if any(host == x or host.endswith("." + x) for x in ("reuters.com", "bloomberg.com", "ft.com")):
        return "established_reporting"
    if any(host == x or host.endswith("." + x) for x in ("x.com", "twitter.com", "reddit.com")):
        return "social"
    return "other"


def publisher_identity(source: Source) -> str:
    host = (urlsplit(source.url).hostname or "").removeprefix("www.").lower()
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    compound_suffixes = {"co.uk", "org.uk", "com.au", "co.jp"}
    width = 3 if ".".join(parts[-2:]) in compound_suffixes else 2
    return ".".join(parts[-width:])


def retrieval_verified(source: Source, state: CognitiveState) -> bool:
    host = (urlsplit(source.url).hostname or "").lower()
    if source.source.lower() != host or source.content_hash != digest(source.content):
        return False
    if source.synthetic:
        return state.mode == "demo"
    if source.source_id != "src_" + digest(source.url + source.content)[:24]:
        return False
    traced = {
        (sid, row.get("query"))
        for row in state.search_history
        if row.get("status") == "success"
        for sid in row.get("source_ids", [])
    }
    return (source.source_id, source.query) in traced or source.source_id in state.archived_source_ids


def process_evidence(
    items: list[Evidence], sources: list[Source], state: CognitiveState, settings: Settings
) -> list[Evidence]:
    source_map = {s.source_id: s for s in sources}
    result = []
    for original in items:
        ev = original.model_copy(deep=True)
        ev.exclusion_reasons = []  # Recalculate against this run's cutoff.
        refs = [source_map[x] for x in ev.source_ids if x in source_map]
        if len(refs) != len(ev.source_ids):
            ev.exclusion_reasons.append("unknown source_id")
        if not refs:
            ev.supported = False
            result.append(ev)
            continue
        ev.synthetic = all(s.synthetic for s in refs)
        ev.retrieval_verified = len(refs) == len(ev.source_ids) and all(
            retrieval_verified(s, state) for s in refs
        )
        if not ev.retrieval_verified:
            ev.exclusion_reasons.append("source provenance not verified in retrieval trace or archive")
        ev.supported = all(normalize(ev.supporting_quote) in normalize(s.content) for s in refs)
        if not ev.supported:
            ev.exclusion_reasons.append("supporting quote not found verbatim in referenced content")
        for source in refs:
            ev.exclusion_reasons.extend(source_exclusions(source, state))
        dates = [s.published_at for s in refs if s.published_at]
        ev.published_at = max(dates) if len(dates) == len(refs) else None
        ev.retrieved_at = max(s.retrieved_at for s in refs)
        ev.source_kind, ev.credibility = max((source_quality(s) for s in refs), key=lambda x: x[1])
        ev.source_type = source_type(max(refs, key=lambda s: source_quality(s)[1]), state)
        ev.source_reliability = (
            "high" if ev.credibility >= 0.8 else "medium" if ev.credibility >= 0.35 else "low"
        )
        ev.support_level = "unreviewed"
        ev.first_hand = False
        ev.corroboration_candidate_ids = []
        ev.quality_score = 0
        # Model-generated claims are never upgraded automatically to verified facts.
        if ev.epistemic_status == "Verified Fact":
            ev.epistemic_status = "Reported Claim"
        if ev.event_status == "completed" and ev.event_at and ev.event_at > state.as_of:
            ev.exclusion_reasons.append("completed event occurs after as_of")
        if ev.effective_at and ev.effective_at > state.as_of and ev.event_status == "completed":
            ev.exclusion_reasons.append("fact effective after as_of")
        ev.stale = bool(ev.published_at and (state.as_of - ev.published_at).days > settings.stale_days)
        if ev.credibility < 0.35:
            ev.exclusion_reasons.append("source below evidence admission threshold")
        # Ignore LLM-provided grouping labels; use a conservative observable event key.
        day = (
            (ev.event_at or ev.published_at).date().isoformat()
            if (ev.event_at or ev.published_at)
            else "unknown"
        )
        key = f"{ev.entity.lower()}|{ev.category}|{day}|{ev.event_status}|{normalize(ev.claim)}"
        ev.event_cluster = "cluster_" + digest(key)[:16]
        ev.exclusion_reasons = sorted(set(ev.exclusion_reasons))
        result.append(ev)
    return deduplicate_evidence(result)


def deduplicate_evidence(items: list[Evidence]) -> list[Evidence]:
    """Keep provenance for every article, but mark syndications so they cannot add weight."""
    representatives = []
    for ev in sorted(items, key=lambda e: (bool(e.exclusion_reasons), -e.credibility, e.evidence_id)):
        # Clear only the dedup marker when recalculating across a larger retrieval set.
        ev.exclusion_reasons = [r for r in ev.exclusion_reasons if not r.startswith("duplicate event:")]
        for previous in representatives:
            a, b = normalize(ev.supporting_quote), normalize(previous.supporting_quote)
            title_similarity = SequenceMatcher(None, normalize(ev.claim), normalize(previous.claim)).ratio()
            same = a == b or (
                ev.category == previous.category
                and ev.event_status == previous.event_status
                and title_similarity > 0.84
            )
            if same:
                ev.event_cluster = previous.event_cluster
                ev.exclusion_reasons.append("duplicate event: " + previous.evidence_id)
                break
        else:
            representatives.append(ev)
    return items


def safe_excerpt(source: Source, max_chars: int = 3600) -> dict:
    value = source.model_dump(mode="json")
    # Rank substantive paragraphs rather than feeding only the site's navigation menu.
    terms = (
        "openai",
        "valuation",
        "revenue",
        "funding",
        "financing",
        "cost",
        "profit",
        "regulat",
        "competition",
    )
    paragraphs = []
    for match in re.finditer(r"[^\n]+", source.content):
        line = match.group().strip()
        if len(line) < 60 or line.startswith(("* [", "- [", "[!", "![")):
            continue
        score = sum(line.casefold().count(term) * (3 if term == "openai" else 1) for term in terms)
        # Even a paragraph without keywords is preferable to an all-navigation fallback.
        paragraphs.append((score, match.start(), match.group()))
    selected, remaining = [], max_chars
    for _, offset, paragraph in sorted(paragraphs, key=lambda x: (-x[0], x[1])):
        if remaining <= 0:
            break
        text = paragraph[:remaining]
        selected.append((offset, text))
        remaining -= len(text) + 5
    selected.sort()
    # Keep full raw source untouched; source offsets locate excerpts in the archive.
    value["content"] = (
        "\n...\n".join(text for _, text in selected) if selected else source.content[:max_chars]
    )
    value["excerpt_source_offsets"] = [offset for offset, _ in selected]
    value["content_truncated_for_model"] = len(source.content) > max_chars
    return value
