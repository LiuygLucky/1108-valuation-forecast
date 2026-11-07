from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_demo_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FORECAST_REPORTS_DIR", str(tmp_path / "reports"))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app/streamlit_app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    assert len(app.tabs) == 4
    app.sidebar.radio[0].set_value("DEMO / SYNTHETIC 离线演示").run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["forecast_state"].status == "complete"
    assert len(app.get("plotly_chart")) == 2
    assert len(app.get("download_button")) == 3
    assert any(m.value == "100.00%" for m in app.metric)
    assert len(list((tmp_path / "reports").glob("*/report.md"))) == 1
    app.button[0].click().run()
    assert not app.exception
    selected = app.selectbox[0].value
    assert selected not in app.selectbox[1].options


def test_dashboard_missing_real_anchor_is_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_DATA_DIR", str(tmp_path / "data"))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app/streamlit_app.py"), default_timeout=30)
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert app.error and "NPM" in app.error[0].value
