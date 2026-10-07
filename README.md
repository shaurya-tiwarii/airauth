# AirAuth

Air-signature biometric authentication: draw a gesture in the air (webcam + MediaPipe hand tracking) and AirAuth verifies you on **two signals** — the *shape* of the trajectory (normalized, resampled, turning-angle features matched with Sakoe-Chiba DTW) and the *behavior* (velocity / acceleration / tilt statistics from the motion kinematics).

Three enrollment passes are fused into one master template via DTW Barycenter Averaging, stored AES-256-GCM encrypted in SQLite. Verification is 70/30 score-level fusion against a calibrated threshold.

FastAPI backend + React/Vite frontend.

## Run backend

```powershell
cd backend
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirement.txt
cd ..
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
```

Backend test: http://127.0.0.1:8000/health

### Master key

The template vault is encrypted with AES-256-GCM. The key is **never in source code**:

1. Set `AIRAUTH_MASTER_KEY` (64 hex chars) — recommended, or
2. On first run the backend generates one and stores it in `backend/.airauth_key` (0600 perms, git-ignored).

Back it up: lose the key and enrolled templates are unrecoverable (by design).

## Run frontend

Open a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL, normally http://localhost:3000.

Point the frontend at a non-local backend with `VITE_API_BASE`:

```powershell
$env:VITE_API_BASE="http://192.168.1.10:8000"; npm run dev
```

## Evaluate (don't guess the threshold)

```powershell
cd backend
# Pipeline smoke test on synthetic gestures (not a real evaluation):
python eval.py --synthetic
# Real evaluation on recorded attempts:
python eval.py attempts.json
```

`attempts.json` is a list of `{"user_id", "points", "kinematics", "label": "genuine"|"impostor"}`. Enroll each user first, then record genuine and impostor attempts and let the harness print the FAR/FRR sweep so `config.THRESHOLD` is chosen from data.

## Tests

```powershell
cd backend
python -m pytest tests/ -q
```

## UI assets

The live sky background uses the video supplied as `frontend/public/foundable-sky.mp4`. The cloud element above the authentication modal uses `frontend/public/cloud-mascot.png`.

The distributed project contains no enrolled biometric database. The default user is `shaurya_01`.

## Threat model & limitations (read before calling this "secure")

- **No liveness detection.** A video recording of your gesture, or shoulder-surfing, can defeat shape matching. Behavioral features raise the bar but are not evaluated against skilled forgeries here.
- **Biometrics are irrevocable.** You cannot rotate your hand motion like a password. If a template is ever decrypted, the user must pick a completely new gesture. Cancelable-biometric transforms are future work.
- **Local prototype scope.** The vault, key file, and API all assume a trusted local machine. There is no rate limiting, no brute-force lockout, and CORS is dev-only.
- **Threshold is a starting point.** `config.THRESHOLD = 16.5` is a prior, not a measurement. Run `eval.py` on real attempts and set the operating point from the FAR/FRR curve for your users.
