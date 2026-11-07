from datetime import UTC, datetime

import numpy as np
import pytest
from pydantic import ValidationError

from forecast_agent.belief import analytic_baseline, baseline_samples, map_intervals
from forecast_agent.config import load_rules, load_settings
from forecast_agent.schemas import NPMObservation, Source


def anchor():
    return NPMObservation(
        valuation_trillion=1,
        source_url=load_rules().source_url,
        effective_date="2026-11-01",
        observed_at=datetime(2026, 11, 2, tzinfo=UTC),
        archive_path="SYNTHETIC",
        archive_sha256="demo",
        verified=True,
        synthetic=True,
    )


def test_boundary_partition():
    values = np.array([0.001, 0.85, 1, 1.15, 1.30, 1.45, 1.4500001, 100])
    p = map_intervals(values, load_rules())
    assert [x.probability for x in p] == [1 / 8, 1 / 8, 1 / 8, 1 / 8, 2 / 8, 2 / 8]


def test_reproducible_and_analytic_agreement():
    rules, settings = load_rules(), load_settings()
    a = baseline_samples(anchor(), rules, settings)
    assert np.array_equal(a, baseline_samples(anchor(), rules, settings))
    p = map_intervals(a, rules)
    assert sum(x.probability for x in p) == pytest.approx(1)
    assert np.allclose([x.probability for x in p], analytic_baseline(anchor(), rules, settings), atol=0.01)


def test_reject_gap_and_naive_time():
    data = load_rules().model_dump()
    data["intervals"][1]["lower_closed"] = False
    with pytest.raises(ValidationError):
        type(load_rules()).model_validate(data)
    with pytest.raises(ValidationError):
        Source(
            source_id="s",
            title="x",
            url="https://example.org",
            source="example.org",
            content="x",
            content_hash="x",
            query="x",
            retrieved_at=datetime(2026, 11, 1),
        )
