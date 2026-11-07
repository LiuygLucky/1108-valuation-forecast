"""Explicit integration probe. Saves real search sources but never fabricates a forecast."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from forecast_agent.clients import Budget, CompatibleLLM, ProviderError, TavilySearch
from forecast_agent.config import ROOT, Secrets, load_rules, load_settings
from forecast_agent.schemas import ResearchPlan, Usage, utcnow
from forecast_agent.storage import Store


def main():
    settings, secrets, rules = load_settings(), Secrets(), load_rules()
    budget = Budget(settings, secrets, Usage())
    store = Store(ROOT / "data/live/forecast.sqlite3")
    results = {"checked_at": utcnow().isoformat(), "forecast_completed": False}
    try:
        sources = TavilySearch(secrets, settings, budget).search(
            "OpenAI revenue financing valuation November 2026 Reuters official NPM"
        )
        for source in sources:
            store.save_source(source)
        results["tavily"] = {
            "status": "ok",
            "sources": [
                {
                    "source_id": s.source_id,
                    "url": s.url,
                    "published_at": s.published_at.isoformat() if s.published_at else None,
                    "retrieved_at": s.retrieved_at.isoformat(),
                }
                for s in sources
            ],
        }
    except ProviderError as exc:
        results["tavily"] = {"status": "failed", "reason": str(exc)}
    print("Tavily probe finished", flush=True)
    try:
        plan = CompatibleLLM(secrets, settings, budget).generate(
            "Return a concise research plan with two items; no factual claims or probabilities.",
            {"question": rules.question},
            ResearchPlan,
        )
        results["llm"] = {"status": "ok", "model": secrets.llm_model, "plan": plan.model_dump()}
    except ProviderError as exc:
        results["llm"] = {"status": "failed", "model": secrets.llm_model, "reason": str(exc)}
    print("LLM probe finished", flush=True)
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(rules.source_url)
        results["npm"] = {
            "http_status": response.status_code,
            "qualified_anchor": False,
            "note": "HTTP access alone does not verify NPM Valuation; a human-verified archived observation is required.",
        }
    except httpx.HTTPError as exc:
        results["npm"] = {"status": "failed", "qualified_anchor": False, "reason": type(exc).__name__}
    results["usage"] = budget.usage.model_dump()
    directory = ROOT / "reports" / ("integration_" + utcnow().strftime("%Y%m%dT%H%M%SZ"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "checks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "report.md").write_text(
        "# 真实接口检查（不是预测报告）\n\n未取得合格 NPM 锚点，因此未生成真实估值概率。\n\n```json\n"
        + json.dumps(results, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=True, indent=2))
    print("Saved: " + str(directory))


if __name__ == "__main__":
    main()
