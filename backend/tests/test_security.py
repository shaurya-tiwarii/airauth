"""Unit tests for the AirAuth biometric core."""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from security import (
    resample_path,
    extract_shape_features,
    extract_behavioral_profile,
    compute_pairwise_dtw,
    dtw_barycenter_averaging,
    SecureBiometricVault,
    match_against_fused_template,
)
import config


def _line(n=40):
    t = np.linspace(0, 1, n)
    return [[float(x), 0.0] for x in t]


def _kin(n=40):
    return [[i / n, 0.0, i * 16.7, 0.0] for i in range(n)]


def test_resample_uniform_spacing():
    pts = np.array(_line(40))
    out = resample_path(pts, target_n=32)
    assert out.shape == (32, 2)
    dists = np.linalg.norm(np.diff(out, axis=0), axis=1)
    assert np.allclose(dists, dists[0], atol=1e-9)


def test_resample_static_raises():
    with pytest.raises(ValueError):
        resample_path(np.zeros((10, 2)))


def test_shape_features_output_shape():
    feats = extract_shape_features(_line(40))
    assert feats.shape == (config.TARGET_POINTS, 3)


def test_shape_features_too_few_points():
    with pytest.raises(ValueError):
        extract_shape_features([[0, 0], [1, 1]])


def test_dtw_identity_zero():
    seq = extract_shape_features(_line(40))
    dist, _ = compute_pairwise_dtw(seq, seq)
    assert dist == pytest.approx(0.0, abs=1e-9)


def test_dtw_symmetric():
    a = extract_shape_features(_line(40))
    b = extract_shape_features([[x, 0.05 * x] for x, _ in _line(40)])
    d1, _ = compute_pairwise_dtw(a, b)
    d2, _ = compute_pairwise_dtw(b, a)
    assert d1 == pytest.approx(d2, rel=1e-6)


def test_behavioral_profile_insufficient_raises():
    with pytest.raises(ValueError):
        extract_behavioral_profile([[0, 0, 0, 0]])


def test_vault_roundtrip():
    db = tempfile.mktemp(suffix=".db")
    vault = SecureBiometricVault(db_path=db)
    passes = [{"points": _line(40), "kinematics": _kin(40)} for _ in range(3)]
    vault.save_fused_template("u1", passes)
    stored = vault.load_fused_template("u1")
    assert stored["master_shape"].shape == (config.TARGET_POINTS, 3)
    assert stored["master_behavior"].shape == (16,)
    Path(db).unlink(missing_ok=True)


def test_vault_unknown_user():
    db = tempfile.mktemp(suffix=".db")
    vault = SecureBiometricVault(db_path=db)
    with pytest.raises(LookupError):
        vault.load_fused_template("nobody")
    Path(db).unlink(missing_ok=True)


def test_match_genuine_accepts():
    db = tempfile.mktemp(suffix=".db")
    vault = SecureBiometricVault(db_path=db)
    passes = [{"points": _line(60), "kinematics": _kin(60)} for _ in range(3)]
    vault.save_fused_template("u1", passes)
    stored = vault.load_fused_template("u1")
    ok, cost, _, _, margin = match_against_fused_template(
        _line(60), _kin(60), stored, threshold=config.THRESHOLD
    )
    assert ok and margin > 0
    Path(db).unlink(missing_ok=True)


def test_match_missing_kinematics_raises():
    db = tempfile.mktemp(suffix=".db")
    vault = SecureBiometricVault(db_path=db)
    passes = [{"points": _line(60), "kinematics": _kin(60)} for _ in range(3)]
    vault.save_fused_template("u1", passes)
    stored = vault.load_fused_template("u1")
    with pytest.raises(ValueError):
        match_against_fused_template(_line(60), [], stored, threshold=config.THRESHOLD)
    Path(db).unlink(missing_ok=True)
