import math
from datetime import date, timedelta

from src.trust_score.components import recency as rc


def test_missing_date_returns_03(make_raw, today):
    raw = make_raw(published_date=None)
    assert rc.score(raw, {}, today=today) == rc.MISSING_DATE_SCORE


def test_today_date_score_one(make_raw, today):
    raw = make_raw(published_date=today)
    assert abs(rc.score(raw, {}, today=today) - 1.0) < 1e-9


def test_general_decay(make_raw, today):
    raw = make_raw(published_date=today - timedelta(days=730))
    s = rc.score(raw, {}, today=today)
    assert abs(s - math.exp(-1.0)) < 1e-9  # exactly one tau old


def test_medical_decay_uses_longer_tau(make_raw, today):
    raw = make_raw(published_date=today - timedelta(days=730))
    s = rc.score(raw, {"is_medical": True}, today=today)
    assert s > math.exp(-1.0)
    assert abs(s - math.exp(-730 / rc.MEDICAL_TAU_DAYS)) < 1e-9


def test_future_date_clamped(make_raw, today):
    future = today + timedelta(days=100)
    raw = make_raw(published_date=future)
    assert rc.score(raw, {}, today=today) == 1.0


def test_old_content_decays_toward_zero(make_raw, today):
    raw = make_raw(published_date=today - timedelta(days=10_000))
    s = rc.score(raw, {}, today=today)
    assert 0.0 < s < 0.001


def test_default_today_when_omitted(make_raw):
    raw = make_raw(published_date=date(2020, 1, 1))
    s = rc.score(raw, {})
    assert 0.0 < s < 1.0  # without today, uses date.today() — just confirm bounds
