import pytest

from src.errors import TrustScoreError, WeightValidationError
from src.trust_score.weights import WEIGHT_KEYS, WEIGHTS, validate_weights


def test_default_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_default_weights_pass_validation():
    validate_weights(WEIGHTS)


def test_missing_key_raises():
    bad = {k: v for k, v in WEIGHTS.items() if k != "recency"}
    with pytest.raises(WeightValidationError) as exc:
        validate_weights(bad)
    assert "recency" in exc.value.details["missing"]


def test_extra_key_raises():
    bad = {**WEIGHTS, "made_up": 0.0}
    with pytest.raises(WeightValidationError) as exc:
        validate_weights(bad)
    assert "made_up" in exc.value.details["extra"]


def test_out_of_range_raises():
    bad = {**WEIGHTS, "recency": 1.1}
    with pytest.raises(WeightValidationError):
        validate_weights(bad)
    bad = {**WEIGHTS, "recency": -0.01}
    with pytest.raises(WeightValidationError):
        validate_weights(bad)


def test_non_numeric_raises():
    bad = {**WEIGHTS, "recency": "0.2"}
    with pytest.raises(WeightValidationError):
        validate_weights(bad)
    bad = {**WEIGHTS, "recency": True}  # bools are int subclass — should reject
    with pytest.raises(WeightValidationError):
        validate_weights(bad)


def test_sum_off_raises():
    bad = {**WEIGHTS, "recency": WEIGHTS["recency"] + 0.01}
    with pytest.raises(WeightValidationError) as exc:
        validate_weights(bad)
    assert "sum" in exc.value.details


def test_sum_within_tolerance_passes():
    bad = {**WEIGHTS, "recency": WEIGHTS["recency"] + 1e-7}
    validate_weights(bad)  # within 1e-6 tolerance


def test_validate_weights_via_base_exception():
    with pytest.raises(TrustScoreError):
        validate_weights({})


def test_keys_constant_matches_weights():
    assert frozenset(WEIGHTS) == WEIGHT_KEYS
