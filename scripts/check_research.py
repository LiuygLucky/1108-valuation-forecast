"""Live LLM component validation against already archived real sources; NOT a forecast."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forecast_agent.clients import Budget, CompatibleLLM
from forecast_agent.config import ROOT, Secrets, load_settings
from forecast_agent.controller import Controller
from forecast_agent.schemas import utcnow
from forecast_agent.storage import Store


def main():
    store = Store(ROOT / "data/live/forecast.sqlite3")
    settings, secrets = load_settings(), Secrets()
    controller = Controller(store, settings=settings, secrets=secrets)
    state = controller.create_state("live")
    state.run_id = "component_" + utcnow().strftime("%Y%m%dT%H%M%SZ")
    state.sources = store.sources(False)
    state.warnings.append(
        "REAL COMPONENT CHECK ONLY: no NPM anchor, no probability forecast, not a completed workflow run"
    )
    controller.budget = Budget(settings, secrets, state.usage)
    controller.llm = CompatibleLLM(secrets, settings, controller.budget)
    results = {"checked_at": utcnow().isoformat(), "forecast_completed": False, "stages": []}
    for node in ["PlanResearch", "ProcessEvidence", "RetrieveMemory", "Reason", "Critique"]:
        try:
            getattr(controller, node)(state)
            results["stages"].append({"node": node, "status": "ok"})
            print(node + ": ok", flush=True)
        except Exception as exc:
            results["stages"].append({"node": node, "status": "failed", "reason": str(exc)[:500]})
            print(node + ": failed (" + type(exc).__name__ + ")", flush=True)
            break
    results.update(
        evidence_count=len(state.evidence),
        eligible_count=len(state.retrieved_evidence_ids),
        hypotheses_count=len(state.hypotheses),
        usage=state.usage.model_dump(),
    )
    directory = ROOT / "reports" / state.run_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "checks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "audit.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
    (directory / "report.md").write_text(
        "# 真实来源认知组件检查（不是预测报告）\n\n没有合格 NPM 锚点，因此没有生成概率。\n\n```json\n"
        + json.dumps(results, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=True, indent=2))
    print("Saved: " + str(directory))


if __name__ == "__main__":
    main()
