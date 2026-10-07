import sys
from pathlib import Path
from typing import List, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    from security import SecureBiometricVault, match_against_fused_template
except ImportError:
    from backend.security import SecureBiometricVault, match_against_fused_template

try:
    import config
except ImportError:
    from backend import config

app = FastAPI(title="AirAuth Air-Signature Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

vault = SecureBiometricVault()

@app.get("/")
def root():
    return {"service": "AirAuth Air-Signature Backend", "status": "ok", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}


class SignaturePass(BaseModel):
    points: List[Tuple[float, float]]
    kinematics: List[List[float]] = []

class FusedEnrollRequest(BaseModel):
    user_id: str
    passes: List[SignaturePass]

class VerifyRequest(BaseModel):
    user_id: str
    points: List[Tuple[float, float]]
    kinematics: List[List[float]] = []

@app.post("/api/v1/airsig/enroll-fused")
def enroll_fused_signature(payload: FusedEnrollRequest):
    if len(payload.passes) != config.ENROLL_PASSES:
        raise HTTPException(
            status_code=400,
            detail=f"Exactly {config.ENROLL_PASSES} enrollment passes required for DBA template fusion."
        )

    try:
        raw_passes = [{"points": p.points, "kinematics": p.kinematics} for p in payload.passes]
        result = vault.save_fused_template(payload.user_id, raw_passes)
        return {
            "status": "success",
            "message": f"Successfully synthesized and encrypted {config.ENROLL_PASSES}-pass "
                       f"master template for '{payload.user_id}'.",
            "template_shape": result["template_shape"],
        }
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))

@app.post("/api/v1/airsig/verify")
def verify_signature(payload: VerifyRequest):
    try:
        stored = vault.load_fused_template(payload.user_id)
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Decryption failure: {str(err)}")

    try:
        is_auth, total_cost, shape_cost, behav_cost, margin = match_against_fused_template(
            cand_points=payload.points,
            cand_kinematics=payload.kinematics,
            stored=stored,
            threshold=config.THRESHOLD,
        )
        return {
            "authenticated": is_auth,
            "fused_distance": total_cost,
            "shape_distance": shape_cost,
            "behavioral_distance": behav_cost,
            "threshold": config.THRESHOLD,
            # margin > 0: accepted with room; margin < 0: rejected by this much.
            # This is a distance margin, not a probability.
            "margin": margin,
        }
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))
