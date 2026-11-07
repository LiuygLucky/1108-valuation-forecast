"""SQLite append-only forecasts, evidence provenance and resumable checkpoints."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from forecast_agent.schemas import CognitiveState, Evidence, Forecast, NPMObservation, Source, utcnow


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, synthetic INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, synthetic INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, node TEXT NOT NULL,
                created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS checkpoint_run ON checkpoints(run_id, seq);
            CREATE TABLE IF NOT EXISTS forecasts (
                run_id TEXT PRIMARY KEY, as_of TEXT NOT NULL, generated_at TEXT NOT NULL,
                mode TEXT NOT NULL, data TEXT NOT NULL, state TEXT NOT NULL, report TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settlements (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS immutable_forecasts_update BEFORE UPDATE ON forecasts
                BEGIN SELECT RAISE(ABORT, 'Forecasts are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_forecasts_delete BEFORE DELETE ON forecasts
                BEGIN SELECT RAISE(ABORT, 'Forecasts are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_sources_update BEFORE UPDATE ON sources
                BEGIN SELECT RAISE(ABORT, 'Sources are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_observations_update BEFORE UPDATE ON observations
                BEGIN SELECT RAISE(ABORT, 'Observations are immutable'); END;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_source(self, source: Source):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO sources VALUES (?,?,?,?)",
                (source.source_id, source.content_hash, source.synthetic, source.model_dump_json()),
            )

    def sources(self, synthetic: bool = False) -> list[Source]:
        with self.connect() as db:
            return [
                Source.model_validate_json(r[0])
                for r in db.execute("SELECT data FROM sources WHERE synthetic=?", (synthetic,))
            ]

    def save_evidence(self, ev: Evidence) -> str:
        fingerprint = digest(json.dumps([sorted(ev.source_ids), ev.claim, ev.supporting_quote, ev.synthetic]))
        with self.connect() as db:
            existing = db.execute("SELECT id FROM evidence WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing:
                return existing[0]
            ev.evidence_id = "ev_" + fingerprint[:24]
            db.execute(
                "INSERT INTO evidence VALUES (?,?,?,?)",
                (ev.evidence_id, fingerprint, ev.synthetic, ev.model_dump_json()),
            )
        return ev.evidence_id

    def evidence(self, synthetic: bool = False) -> list[Evidence]:
        with self.connect() as db:
            return [
                Evidence.model_validate_json(r[0])
                for r in db.execute("SELECT data FROM evidence WHERE synthetic=?", (synthetic,))
            ]

    def save_observation(self, obs: NPMObservation):
        with self.connect() as db:
            db.execute("INSERT INTO observations VALUES (?,?)", (obs.observation_id, obs.model_dump_json()))

    def observations(self) -> list[NPMObservation]:
        with self.connect() as db:
            return [
                NPMObservation.model_validate_json(r[0]) for r in db.execute("SELECT data FROM observations")
            ]

    def checkpoint(self, state: CognitiveState, node: str):
        with self.connect() as db:
            db.execute(
                "INSERT INTO checkpoints(run_id,node,created_at,data) VALUES (?,?,?,?)",
                (state.run_id, node, utcnow().isoformat(), state.model_dump_json()),
            )

    def resume(self, run_id: str) -> CognitiveState:
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)
            ).fetchone()
        if not row:
            raise ValueError("Unknown run ID")
        return CognitiveState.model_validate_json(row[0])

    def trace(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                dict(zip(("seq", "node", "created_at"), r, strict=True))
                for r in db.execute(
                    "SELECT seq,node,created_at FROM checkpoints WHERE run_id=? ORDER BY seq", (run_id,)
                )
            ]

    def last_completed_review(self, run_id: str) -> CognitiveState | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM checkpoints WHERE run_id=? AND node='Critique' ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return CognitiveState.model_validate_json(row[0]) if row else None

    def save_forecast(self, state: CognitiveState):
        if state.forecast is None:
            raise ValueError("Missing forecast")
        forecast = state.forecast
        with self.connect() as db:
            old = db.execute("SELECT data FROM forecasts WHERE run_id=?", (state.run_id,)).fetchone()
            if old:
                if old[0] != forecast.model_dump_json():
                    raise ValueError("Cannot overwrite an immutable forecast")
                return  # Idempotent recovery of the SaveRun node.
            db.execute(
                "INSERT INTO forecasts VALUES (?,?,?,?,?,?,?)",
                (
                    state.run_id,
                    state.as_of.isoformat(),
                    forecast.generated_at.isoformat(),
                    state.mode,
                    forecast.model_dump_json(),
                    state.model_dump_json(),
                    state.report,
                ),
            )

    def history(self, mode: str | None = None) -> list[Forecast]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT data FROM forecasts WHERE (? IS NULL OR mode=?) ORDER BY as_of DESC, generated_at DESC",
                (mode, mode),
            ).fetchall()
        return [Forecast.model_validate_json(r[0]) for r in rows]

    def saved_state(self, run_id: str) -> CognitiveState:
        with self.connect() as db:
            row = db.execute("SELECT state FROM forecasts WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("Unknown completed run")
        return CognitiveState.model_validate_json(row[0])
