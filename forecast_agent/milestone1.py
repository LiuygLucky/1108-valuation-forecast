"""Executable M1 vertical slice; full cognitive workflow is implemented in controller.py."""

import json
from pathlib import Path

from forecast_agent.belief import baseline_samples, map_intervals
from forecast_agent.clients import Budget, CompatibleLLM, TavilySearch
from forecast_agent.config import ROOT, Secrets, load_rules, load_settings
from forecast_agent.demo import DEMO_AS_OF, DemoLLM, DemoSearch, demo_anchor
from forecast_agent.observations import select_anchor
from forecast_agent.schemas import EvidenceBatch, Usage, uid, utcnow
from forecast_agent.storage import Store


def run_minimal(mode="demo", output: Path | None = None, secrets: Secrets | None = None):
    settings, rules = load_settings(), load_rules()
    secrets = secrets or Secrets()
    store = Store(ROOT / "data" / mode / "forecast.sqlite3")
    usage = Usage()
    if mode == "demo":
        as_of, anchor, search, llm = DEMO_AS_OF, demo_anchor(rules), DemoSearch(), DemoLLM()
    elif mode == "live":
        as_of = utcnow()
        anchor = select_anchor(store, as_of, rules, settings)
        budget = Budget(settings, secrets, usage)
        search, llm = TavilySearch(secrets, settings, budget), CompatibleLLM(secrets, settings, budget)
    else:
        raise ValueError("M1 supports demo/live only")
    sources = search.search("OpenAI revenue profitability financing latest Reuters official")
    for source in sources:
        store.save_source(source)
    analysis = llm.generate(
        "Extract evidence with exact <=25 word source quotes; no invented dates.",
        {"sources": [s.model_dump(mode="json") for s in sources]},
        EvidenceBatch,
    )
    result = {
        "run_id": uid("m1"),
        "milestone": "M1 baseline-only vertical slice",
        "mode": mode,
        "as_of": as_of.isoformat(),
        "anchor": anchor.model_dump(mode="json"),
        "probabilities": [
            p.model_dump() for p in map_intervals(baseline_samples(anchor, rules, settings), rules)
        ],
        "analysis_unreviewed": analysis.model_dump(mode="json"),
        "usage": usage.model_dump(),
    }
    path = output or ROOT / "reports" / f"{result['run_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    return result


if __name__ == "__main__":
    print(json.dumps(run_minimal(), ensure_ascii=True, indent=2))
