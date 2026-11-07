from datetime import UTC, datetime

from forecast_agent.config import load_rules
from forecast_agent.demo import demo_anchor
from forecast_agent.evaluation import settle
from forecast_agent.storage import Store


def test_unresolved_before_target_and_without_finality(tmp_path):
    store = Store(tmp_path / "test.db")
    assert settle(store, load_rules(), None)["status"] == "UNRESOLVED"
    obs = demo_anchor(load_rules())
    store.save_observation(obs)
    assert (
        settle(store, load_rules(), obs.observation_id, True, datetime(2027, 1, 1, tzinfo=UTC))["status"]
        == "UNRESOLVED"
    )


def test_archived_latest_resolution_and_boundary(tmp_path):
    import hashlib

    store = Store(tmp_path / "test.db")
    archive = tmp_path / "manual-test-archive.txt"
    archive.write_text("TEST ONLY, synthetic test of archive validation", encoding="utf-8")
    obs = demo_anchor(load_rules()).model_copy(
        update={
            "synthetic": False,
            "valuation_trillion": 1.45,
            "effective_date": datetime(2026, 12, 31).date(),
            "observed_at": datetime(2027, 1, 1, tzinfo=UTC),
            "archive_path": str(archive),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
    )
    store.save_observation(obs)
    result = settle(store, load_rules(), obs.observation_id, True, datetime(2027, 1, 2, tzinfo=UTC))
    assert result["status"] == "RESOLVED" and result["outcome_index"] == 4
    assert result["settlement_effective_date"] == "2026-12-31"
    archive.write_text("modified", encoding="utf-8")
    assert (
        settle(store, load_rules(), obs.observation_id, True, datetime(2027, 1, 2, tzinfo=UTC))["status"]
        == "UNRESOLVED"
    )
