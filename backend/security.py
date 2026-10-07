"""AirAuth biometric core: feature extraction, DTW matching, encrypted vault.

Canonical module (replaces the old duplicated secure_storage.py).
All tunables live in config.py.
"""
import os
import json
import sqlite3
from pathlib import Path
from typing import List, Tuple, Dict, Any
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import (
    TARGET_POINTS, DTW_BAND, DBA_ITERATIONS,
    FUSION_W_SHAPE, FUSION_W_BEHAVIOR, BEHAVIOR_SCALE,
    MIN_POINTS, MIN_KINEMATICS,
)

DB_FILE = str(Path(__file__).resolve().parent / "airauth_secure.db")
KEY_FILE = str(Path(__file__).resolve().parent / ".airauth_key")


def _load_master_key() -> bytes:
    """Master key for the template vault. Never hardcoded.

    Priority: AIRAUTH_MASTER_KEY env var -> .airauth_key file
    (created once with 0600 perms) -> generate and persist a fresh key.

    The env var accepts either a hex-encoded 32-byte key (classic form)
    or any opaque string (e.g. a platform-generated secret); the latter
    is stretched to 32 bytes with SHA-256 so generated secrets from
    hosts like Render work without manual hex conversion.
    """
    import hashlib

    key_env = os.environ.get("AIRAUTH_MASTER_KEY")
    if key_env:
        raw = key_env.strip()
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            key = hashlib.sha256(raw.encode("utf-8")).digest()
        if len(key) != 32:
            raise RuntimeError("AIRAUTH_MASTER_KEY must decode to 32 bytes (AES-256).")
        return key

    key_path = Path(KEY_FILE)
    if key_path.exists():
        key = bytes.fromhex(key_path.read_text().strip())
        if len(key) != 32:
            raise RuntimeError(f"Key file {KEY_FILE} is corrupt (not 32 bytes).")
        return key

    key = AESGCM.generate_key(bit_length=256)
    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key.hex())
    return key


def resample_path(pts: np.ndarray, target_n: int = TARGET_POINTS) -> np.ndarray:
    deltas = np.diff(pts, axis=0)
    segment_lengths = np.sqrt(np.sum(deltas ** 2, axis=1))
    cum_dist = np.insert(np.cumsum(segment_lengths), 0, 0.0)
    total_length = cum_dist[-1]

    if total_length == 0:
        raise ValueError("Static gesture detected.")

    interp_dists = np.linspace(0.0, total_length, target_n)
    rx = np.interp(interp_dists, cum_dist, pts[:, 0])
    ry = np.interp(interp_dists, cum_dist, pts[:, 1])
    return np.column_stack((rx, ry))


def extract_shape_features(raw_points: List[Tuple[float, float]],
                           target_n: int = TARGET_POINTS) -> np.ndarray:
    pts = np.array(raw_points, dtype=np.float64)
    if len(pts) < MIN_POINTS:
        raise ValueError("Insufficient points recorded.")

    pts -= np.mean(pts, axis=0)

    max_span = np.max(np.ptp(pts, axis=0))
    if max_span > 0:
        pts /= max_span

    uniform_pts = resample_path(pts, target_n=target_n)

    diffs = np.diff(uniform_pts, axis=0)
    headings = np.arctan2(diffs[:, 1], diffs[:, 0])
    turn_angles = np.diff(headings)
    turn_angles = (turn_angles + np.pi) % (2 * np.pi) - np.pi
    turn_angles = np.pad(turn_angles, (1, 1), mode='edge').reshape(-1, 1)

    return np.hstack((uniform_pts, np.sin(turn_angles) * 0.5))


def extract_behavioral_profile(kinematics: List[List[float]]) -> np.ndarray:
    if not kinematics or len(kinematics) < MIN_KINEMATICS:
        raise ValueError(
            "Insufficient motion data recorded; draw the gesture in one continuous motion."
        )

    arr = np.array(kinematics, dtype=np.float64)
    coords = arr[:, :2]
    times = arr[:, 2] / 1000.0
    angles = arr[:, 3]

    dt = np.diff(times)
    dt[dt <= 0] = 0.016

    dist = np.sqrt(np.sum(np.diff(coords, axis=0) ** 2, axis=1))
    speeds = dist / dt
    accel = np.diff(speeds) / dt[:-1]

    v_mean = np.mean(speeds)
    v_std = np.std(speeds)
    v_max = np.max(speeds)
    v_median = np.median(speeds)

    a_std = np.std(accel) if len(accel) > 0 else 0.0
    a_max = np.max(np.abs(accel)) if len(accel) > 0 else 0.0

    angle_mean = np.mean(angles)
    angle_std = np.std(angles)

    hist, _ = np.histogram(speeds, bins=8, density=True)
    stats = np.array([v_mean, v_std, v_max, v_median, a_std, a_max, angle_mean, angle_std],
                     dtype=np.float64)
    profile = np.concatenate([stats, hist.astype(np.float64)])
    norm = np.linalg.norm(profile)
    return profile / norm if norm > 0 else profile


def compute_pairwise_dtw(s1: np.ndarray, s2: np.ndarray,
                         w: int = DTW_BAND) -> Tuple[float, List[Tuple[int, int]]]:
    n, m = len(s1), len(s2)
    w = max(w, abs(n - m))

    cost = np.linalg.norm(s1[:, None, :] - s2[None, :, :], axis=-1)
    dtw = np.full((n + 1, m + 1), np.inf)
    dtw[0, 0] = 0.0

    for i in range(1, n + 1):
        j_start = max(1, i - w)
        j_end = min(m, i + w)
        for j in range(j_start, j_end + 1):
            dtw[i, j] = cost[i - 1, j - 1] + min(
                dtw[i - 1, j],
                dtw[i, j - 1],
                dtw[i - 1, j - 1]
            )

    path: List[Tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        scores = [dtw[i - 1, j - 1], dtw[i - 1, j], dtw[i, j - 1]]
        min_idx = int(np.argmin(scores))
        if min_idx == 0:
            i -= 1
            j -= 1
        elif min_idx == 1:
            i -= 1
        else:
            j -= 1

    while i > 0:
        path.append((i - 1, 0))
        i -= 1
    while j > 0:
        path.append((0, j - 1))
        j -= 1

    return float(dtw[n, m]), path[::-1]


def dtw_barycenter_averaging(samples: List[np.ndarray],
                             iterations: int = DBA_ITERATIONS) -> np.ndarray:
    barycenter = np.copy(samples[0])
    n_points, _ = barycenter.shape

    for _ in range(iterations):
        associations: List[List[np.ndarray]] = [[] for _ in range(n_points)]
        for seq in samples:
            _, path = compute_pairwise_dtw(barycenter, seq)
            for b_idx, s_idx in path:
                associations[b_idx].append(seq[s_idx])

        for idx in range(n_points):
            if len(associations[idx]) > 0:
                barycenter[idx] = np.mean(associations[idx], axis=0)

    return barycenter


class SecureBiometricVault:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.master_key = _load_master_key()
        self.aesgcm = AESGCM(self.master_key)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(biometric_vault)")
            columns = [row[1] for row in cursor.fetchall()]

            # Clean schema migration if an outdated table definition exists
            if columns and ("sample_count" in columns or "feature_dim" in columns):
                cursor.execute("DROP TABLE biometric_vault")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS biometric_vault (
                    user_id TEXT PRIMARY KEY,
                    nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def save_fused_template(self, user_id: str, passes: List[Dict[str, Any]]) -> Dict[str, Any]:
        shape_matrices = [extract_shape_features(p["points"]) for p in passes]
        master_shape = dtw_barycenter_averaging(shape_matrices)

        behavior_vectors = [extract_behavioral_profile(p.get("kinematics", [])) for p in passes]
        master_behavior = np.mean(behavior_vectors, axis=0)
        norm = np.linalg.norm(master_behavior)
        if norm > 0:
            master_behavior /= norm

        payload = {
            "master_shape": master_shape.tolist(),
            "master_behavior": master_behavior.tolist()
        }
        payload_bytes = json.dumps(payload).encode('utf-8')

        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, payload_bytes, user_id.encode('utf-8'))

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO biometric_vault (user_id, nonce, ciphertext)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nonce = excluded.nonce,
                    ciphertext = excluded.ciphertext,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, nonce, ciphertext))
            conn.commit()

        return {
            "status": "success",
            "user_id": user_id,
            "passes_synthesized": len(passes),
            "template_shape": list(master_shape.shape),
        }

    def load_fused_template(self, user_id: str) -> Dict[str, np.ndarray]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT nonce, ciphertext FROM biometric_vault WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()

        if not row:
            raise LookupError(f"User '{user_id}' has not enrolled a fused template.")

        nonce, ciphertext = row
        decrypted = self.aesgcm.decrypt(nonce, ciphertext, user_id.encode('utf-8'))
        data = json.loads(decrypted.decode('utf-8'))

        return {
            "master_shape": np.array(data["master_shape"], dtype=np.float64),
            "master_behavior": np.array(data["master_behavior"], dtype=np.float64)
        }


def match_against_fused_template(
    cand_points: List[Tuple[float, float]],
    cand_kinematics: List[List[float]],
    stored: Dict[str, np.ndarray],
    threshold: float,
) -> Tuple[bool, float, float, float, float]:
    """Score-level fusion of shape (DTW) and behavioral (cosine) distances.

    Returns (authenticated, fused_cost, shape_dist, behavior_dist, margin).
    margin = threshold - fused_cost: positive means accepted with room to
    spare, negative means rejected by that amount. It is NOT a probability.
    """
    cand_shape = extract_shape_features(cand_points)
    shape_dist, _ = compute_pairwise_dtw(cand_shape, stored["master_shape"], w=DTW_BAND)

    cand_behavior = extract_behavioral_profile(cand_kinematics)
    behavior_dist = float(1.0 - np.dot(cand_behavior, stored["master_behavior"])) * BEHAVIOR_SCALE

    fused_cost = FUSION_W_SHAPE * shape_dist + FUSION_W_BEHAVIOR * behavior_dist
    is_authenticated = bool(fused_cost <= threshold)
    margin = threshold - fused_cost

    return (is_authenticated, round(fused_cost, 2), round(shape_dist, 2),
            round(behavior_dist, 2), round(margin, 2))
