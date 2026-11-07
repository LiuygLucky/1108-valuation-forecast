import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import AwareDatetime, TypeAdapter

from forecast_agent.config import ROOT, Settings, load_rules, load_settings
from forecast_agent.controller import Controller
from forecast_agent.evaluation import compare_forecasts, score, settle
from forecast_agent.observations import import_observation
from forecast_agent.schemas import MarketRules
from forecast_agent.storage import Store


def parser():
    p = argparse.ArgumentParser(description="Cognitive Forecasting Agent V1 — fixed terminal NPM task")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    p.add_argument("--reports-dir", type=Path, default=ROOT / "reports")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="One bounded cognitive research run")
    run.add_argument("--mode", choices=["live", "historical", "demo"], default="live")
    run.add_argument("--as-of", help="Timezone-aware ISO cutoff; historical mode requires this")
    run.add_argument("--settings", type=Path)
    resume = sub.add_parser("resume", help="Resume original state, settings and rules")
    resume.add_argument("run_id")
    resume.add_argument("--mode", choices=["live", "historical", "demo"], required=True)
    imp = sub.add_parser(
        "import-npm", help="Import manually verified NPM metadata and screenshot/page archive"
    )
    imp.add_argument("metadata", type=Path)
    imp.add_argument("archive", type=Path)
    history = sub.add_parser("history")
    history.add_argument("--mode", choices=["live", "historical", "demo"], default="live")
    compare = sub.add_parser("compare")
    compare.add_argument("previous_run")
    compare.add_argument("current_run")
    compare.add_argument("--mode", choices=["live", "historical", "demo"], default="live")
    resolution = sub.add_parser("settle")
    resolution.add_argument("--observation-id")
    resolution.add_argument(
        "--confirm-latest",
        action="store_true",
        help="Human confirms final/latest qualifying observation as of target date",
    )
    scoring = sub.add_parser("score")
    scoring.add_argument("run_id")
    scoring.add_argument("settlement_id")
    scoring.add_argument("--mode", choices=["live", "historical"], default="live")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    mode = getattr(args, "mode", "live")
    # Historical and live share a real evidence archive; demo is physically isolated.
    store = Store(args.data_dir / ("demo" if mode == "demo" else "live") / "forecast.sqlite3")
    try:
        if args.command in {"run", "resume"}:
            if args.command == "resume":
                state = store.resume(args.run_id)
                if state.mode != mode:
                    raise ValueError("Resume mode does not match the original run")
                controller = Controller(
                    store,
                    settings=Settings.model_validate(state.settings_snapshot),
                    rules=MarketRules.model_validate(state.rules_snapshot),
                    reports=args.reports_dir,
                    on_progress=print_progress,
                )
            else:
                if mode == "historical" and not args.as_of:
                    raise ValueError("Historical mode requires --as-of and archived sources")
                as_of = TypeAdapter(AwareDatetime).validate_python(args.as_of) if args.as_of else None
                controller = Controller(
                    store,
                    settings=load_settings(args.settings),
                    reports=args.reports_dir,
                    on_progress=print_progress,
                )
                state = controller.create_state(mode, as_of)
            print(f"run_id={state.run_id}", file=sys.stderr)
            result = controller.run(state)
            print(result.forecast.model_dump_json(indent=2))
            print(f"Reports: {args.reports_dir / state.run_id}", file=sys.stderr)
        elif args.command == "import-npm":
            print(
                import_observation(args.metadata, args.archive, store, load_rules()).model_dump_json(indent=2)
            )
        elif args.command == "history":
            print(
                json.dumps(
                    [
                        {
                            "run_id": f.run_id,
                            "as_of": f.as_of.isoformat(),
                            "model_version": f.model_version,
                            "probabilities": [p.model_dump() for p in f.probabilities],
                        }
                        for f in store.history(mode)
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif args.command == "compare":
            previous, current = store.saved_state(args.previous_run), store.saved_state(args.current_run)
            print(
                json.dumps(
                    compare_forecasts(previous.forecast, current.forecast), indent=2, ensure_ascii=False
                )
            )
        elif args.command == "settle":
            print(
                json.dumps(
                    settle(store, load_rules(), args.observation_id, args.confirm_latest),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif args.command == "score":
            with store.connect() as db:
                row = db.execute("SELECT data FROM settlements WHERE id=?", (args.settlement_id,)).fetchone()
            if not row:
                raise ValueError("Unknown settlement ID")
            print(json.dumps(score(store.saved_state(args.run_id).forecast, json.loads(row[0])), indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def print_progress(node, state):
    print(f"[{state.run_id}] {node} (iteration {state.iteration_count})", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
