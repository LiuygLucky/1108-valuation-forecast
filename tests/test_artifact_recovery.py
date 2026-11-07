import pytest

import forecast_agent.controller as controller_module
from forecast_agent.controller import Controller
from forecast_agent.storage import Store


def test_resume_after_sqlite_commit_and_partial_export(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    original = controller_module.export_report

    def fail_once(state, root):
        directory = root / state.run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "report.md").write_text(state.report, encoding="utf-8")
        raise OSError("simulated export interruption")

    monkeypatch.setattr(controller_module, "export_report", fail_once)
    c = Controller(store, reports=tmp_path / "reports")
    state = c.create_state("demo")
    with pytest.raises(OSError, match="interruption"):
        c.run(state)
    assert len(store.history()) == 1
    assert store.resume(state.run_id).next_node == "SaveRun"
    monkeypatch.setattr(controller_module, "export_report", original)
    recovered = c.run(store.resume(state.run_id))
    assert recovered.status == "complete" and len(store.history()) == 1
    assert (tmp_path / "reports" / state.run_id / "audit.json").is_file()
