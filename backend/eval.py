"""AirAuth evaluation harness: measure FAR/FRR instead of guessing a threshold.

Usage:
  # Evaluate recorded attempts (JSON list) against enrolled templates:
  python eval.py attempts.json [--threshold T]

  # attempts.json: [{"user_id": "...", "points": [[x,y],...],
  #                  "kinematics": [[x,y,t,tilt],...], "label": "genuine"|"impostor"}]
  # Templates must already be enrolled in the vault for each user_id.

  # Pipeline smoke test on synthetic gestures (NOT a real evaluation):
  python eval.py --synthetic

The sweep prints FAR/FRR across thresholds so the operating point in
config.py can be chosen from data.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from security import SecureBiometricVault, match_against_fused_template, extract_shape_features
import config


def score_attempt(vault: SecureBiometricVault, attempt: dict, threshold: float) -> float:
    stored = vault.load_fused_template(attempt["user_id"])
    _, fused_cost, _, _, _ = match_against_fused_template(
        attempt["points"], attempt.get("kinematics", []), stored, threshold=threshold
    )
    return fused_cost


def sweep(attempts: list, vault: SecureBiometricVault, thresholds: np.ndarray):
    genuine = [a for a in attempts if a["label"] == "genuine"]
    impostor = [a for a in attempts if a["label"] == "impostor"]
    if not genuine or not impostor:
        raise SystemExit("Need at least one genuine and one impostor attempt.")

    g_scores = [score_attempt(vault, a, config.THRESHOLD) for a in genuine]
    i_scores = [score_attempt(vault, a, config.THRESHOLD) for a in impostor]

    print(f"genuine attempts: {len(genuine)}  impostor attempts: {len(impostor)}")
    print(f"{'thr':>7} {'FAR':>7} {'FRR':>7}  (FAR=false accepts, FRR=false rejects)")
    best, best_sum = None, 2.0
    for t in thresholds:
        far = sum(s <= t for s in i_scores) / len(i_scores)
        frr = sum(s > t for s in g_scores) / len(g_scores)
        mark = ""
        if far + frr < best_sum:
            best, best_sum = t, far + frr
            mark = "  <-- lowest FAR+FRR"
        print(f"{t:7.2f} {far:7.3f} {frr:7.3f}{mark}")
    print(f"\nSuggested operating threshold: {best:.2f} (currently config.THRESHOLD={config.THRESHOLD})")


def _synth_gesture(kind: str, n: int = 120, noise: float = 0.01, seed: int = 0):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    if kind == "wave":
        x, y = t, 0.5 + 0.25 * np.sin(6 * np.pi * t)
    else:  # circle-ish impostor
        x = 0.5 + 0.3 * np.cos(2 * np.pi * t)
        y = 0.5 + 0.3 * np.sin(2 * np.pi * t)
    x += rng.normal(0, noise, n)
    y += rng.normal(0, noise, n)
    pts = np.column_stack([x, y])
    times = (np.arange(n) * 16.7).tolist()  # ~60fps
    kin = []
    for i in range(n):
        tilt = float(np.arctan2(y[i] - y[max(0, i - 1)], x[i] - x[max(0, i - 1)] + 1e-9))
        kin.append([float(x[i]), float(y[i]), times[i], tilt])
    return pts.tolist(), kin


def synthetic_smoke():
    print("Synthetic pipeline smoke test (NOT a real biometric evaluation).")
    import tempfile
    db = tempfile.mktemp(suffix=".db")
    vault = SecureBiometricVault(db_path=db)
    passes = [{"points": p, "kinematics": k}
              for p, k in (_synth_gesture("wave", seed=s) for s in range(3))]
    vault.save_fused_template("synth_user", passes)
    attempts = []
    for s in range(10, 20):
        p, k = _synth_gesture("wave", noise=0.02, seed=s)
        attempts.append({"user_id": "synth_user", "points": p, "kinematics": k, "label": "genuine"})
    for s in range(10):
        p, k = _synth_gesture("circle", noise=0.02, seed=s)
        attempts.append({"user_id": "synth_user", "points": p, "kinematics": k, "label": "impostor"})
    sweep(attempts, vault, np.arange(2.0, 30.0, 1.0))
    Path(db).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("attempts", nargs="?", help="JSON file of labeled attempts")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    if args.synthetic:
        return synthetic_smoke()
    if not args.attempts:
        ap.error("provide attempts.json or --synthetic")

    attempts = json.loads(Path(args.attempts).read_text())
    vault = SecureBiometricVault()
    lo = args.threshold - 10 if args.threshold else 2.0
    hi = args.threshold + 10 if args.threshold else 30.0
    sweep(attempts, vault, np.arange(lo, hi, 0.5))


if __name__ == "__main__":
    main()
