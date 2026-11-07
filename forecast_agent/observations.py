import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from forecast_agent.config import Settings
from forecast_agent.schemas import MarketRules, NPMObservation
from forecast_agent.storage import Store


def import_observation(metadata: Path, archive: Path, store: Store, rules: MarketRules) -> NPMObservation:
    """Import a human-verified NPM observation and preserve its original bytes."""
    import json

    data = json.loads(metadata.read_text("utf-8-sig"))
    if not archive.is_file():
        raise ValueError("NPM observation requires an existing screenshot or page archive")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    data.update(archive_sha256=sha, archive_path=str(archive.resolve()))
    obs = NPMObservation.model_validate(data)
    if obs.synthetic or not obs.verified or obs.source_url != rules.source_url:
        raise ValueError("Import requires manually verified, real NPM data at the fixed target URL")
    if obs.effective_date > obs.observed_at.astimezone(ZoneInfo(rules.timezone)).date():
        raise ValueError("Effective date cannot be after the observed business date")
    dest = store.path.parent / "archives" / f"{sha}{archive.suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(archive, dest)
    obs.archive_path = str(dest.resolve())
    store.save_observation(obs)
    return obs


def archive_valid(obs: NPMObservation) -> bool:
    path = Path(obs.archive_path)
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == obs.archive_sha256


def select_anchor(store: Store, as_of: datetime, rules: MarketRules, settings: Settings) -> NPMObservation:
    day = as_of.astimezone(ZoneInfo(rules.timezone)).date()
    candidates = [
        o
        for o in store.observations()
        if o.verified
        and not o.synthetic
        and o.observed_at <= as_of
        and o.effective_date <= min(day, rules.target_date)
        and o.source_url == rules.source_url
        and archive_valid(o)
    ]
    if not candidates:
        raise ValueError(
            "No eligible NPM Valuation anchor. Import a verified NPM observation with its archive."
        )
    anchor = max(candidates, key=lambda o: (o.effective_date, o.observed_at))
    if (day - anchor.effective_date).days > settings.max_anchor_age_days:
        raise ValueError("Latest NPM observation exceeds configured maximum anchor age")
    return anchor
