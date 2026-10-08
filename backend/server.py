import hashlib
import os
import sys
from pathlib import Path
from typing import List, Tuple

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, EmailStr

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    from security import SecureBiometricVault, match_against_fused_template
    import config
    import auth as authmod
    import signstore
    import pdfsign
except ImportError:
    from backend.security import SecureBiometricVault, match_against_fused_template
    from backend import config, auth as authmod, signstore, pdfsign

app = FastAPI(title="AirAuth")

_cors_origins = [o.strip() for o in
                 os.environ.get("AIRAUTH_CORS_ORIGINS",
                                "http://localhost:3000,http://127.0.0.1:3000").split(",")
                 if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

vault = SecureBiometricVault()
signstore.init_db()


# ---- light rate limiting (in-memory sliding window, per instance) ---------

import time
from collections import defaultdict

_rate_hits: dict = defaultdict(list)
RATE_LIMIT_N = int(os.environ.get("AIRAUTH_RATE_LIMIT_N", "30"))
RATE_LIMIT_WINDOW = int(os.environ.get("AIRAUTH_RATE_LIMIT_WINDOW", "60"))

def _check_rate_limit(key: str):
    now = time.monotonic()
    hits = [t for t in _rate_hits[key] if now - t < RATE_LIMIT_WINDOW]
    if len(hits) >= RATE_LIMIT_N:
        raise HTTPException(status_code=429,
                            detail="Too many attempts. Wait a minute and try again.")
    hits.append(now)
    _rate_hits[key] = hits

def _rate_key(request, prefix: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{prefix}:{client}"


def _template_key(uid: int) -> str:
    return f"user:{uid}"


@app.on_event("startup")
def seed_platform_admin():
    # Fail closed: no default credentials are ever created. Set both env vars
    # to seed the platform admin on first boot.
    email = os.environ.get("AIRAUTH_ADMIN_EMAIL")
    password = os.environ.get("AIRAUTH_ADMIN_PASSWORD")
    if not email or not password:
        print("[airauth] AIRAUTH_ADMIN_EMAIL/PASSWORD not set: "
              "no platform admin seeded.")
        return
    if not signstore.get_user_by_email(email):
        try:
            signstore.create_user(email, authmod.hash_password(password),
                                  "Platform Admin", "platform_admin")
            print(f"[airauth] platform admin seeded: {email}")
        except Exception as e:
            print(f"[airauth] admin seed failed: {e}")


# ---------------------------------------------------------------- airsig (original)

@app.get("/")
def root():
    return {"service": "AirAuth", "status": "ok", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}


class SignaturePass(BaseModel):
    points: List[Tuple[float, float]]
    kinematics: List[List[float]] = []

class FusedEnrollRequest(BaseModel):
    user_id: str
    passes: List[SignaturePass]

def _enroll_fused_template(payload: FusedEnrollRequest):
    """Internal only: fuse and encrypt an enrollment template. Never exposed
    as a route, so only the authenticated /auth/enroll wrapper can reach it."""
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
            "message": f"Enrolled and encrypted {config.ENROLL_PASSES}-pass "
                       f"master template for '{payload.user_id}'.",
            "template_shape": result["template_shape"],
        }
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


# ---------------------------------------------------------------- auth

class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "user"           # user | employee | employer_admin
    business_name: str = ""      # required for employer_admin
    invite_code: str = ""        # required for employee

class LoginIn(BaseModel):
    email: EmailStr
    password: str

@app.post("/api/v1/auth/register")
def register(payload: RegisterIn, request: Request):
    _check_rate_limit(_rate_key(request, "register"))
    role = payload.role.strip()
    if role not in ("user", "employee", "employer_admin"):
        raise HTTPException(status_code=400, detail="Invalid role.")
    if signstore.get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered.")
    try:
        pw_hash = authmod.hash_password(payload.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    business_id = None
    if role == "employer_admin":
        if not payload.business_name.strip():
            raise HTTPException(status_code=400, detail="Business name is required.")
    if role == "employee":
        biz = signstore.get_business_by_invite(payload.invite_code)
        if not biz:
            raise HTTPException(status_code=400, detail="Invalid invite code.")
        business_id = biz["id"]

    user = signstore.create_user(payload.email, pw_hash, payload.name, role, business_id)
    business = None
    if role == "employer_admin":
        business = signstore.create_business(payload.business_name, user["id"])
        user = signstore.get_user(user["id"])
    _audit(user["id"], "auth.register", f"role={role}")
    return {"user": authmod.public_user(user),
            "business": business,
            "token": authmod.make_token(user["id"], user["role"])}

@app.post("/api/v1/auth/login")
def login(payload: LoginIn, request: Request):
    _check_rate_limit(_rate_key(request, "login"))
    user = signstore.get_user_by_email(payload.email)
    if not user or not authmod.check_password(payload.password, user["pw_hash"]):
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    _audit(user["id"], "auth.login", "")
    return {"user": authmod.public_user(user),
            "token": authmod.make_token(user["id"], user["role"])}

class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str

@app.post("/api/v1/auth/change-password")
def change_password(payload: ChangePasswordIn,
                    user: dict = Depends(authmod.get_current_user)):
    """Change the logged-in user's password. Requires the current password."""
    if not authmod.check_password(payload.current_password, user["pw_hash"]):
        raise HTTPException(status_code=401, detail="Current password is wrong.")
    try:
        new_hash = authmod.hash_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    signstore.set_password(user["id"], new_hash)
    _audit(user["id"], "auth.change_password", "")
    return {"status": "changed"}

@app.get("/api/v1/auth/me")
def me(user: dict = Depends(authmod.get_current_user)):
    biz = signstore.get_business(user["business_id"]) if user["business_id"] else None
    out = authmod.public_user(user)
    out["business"] = {"id": biz["id"], "name": biz["name"],
                       "invite_code": biz["invite_code"]} if biz else None
    return out

@app.post("/api/v1/auth/enroll")
def enroll_me(payload: FusedEnrollRequest, user: dict = Depends(authmod.get_current_user)):
    """Enroll the logged-in user's air signature (one profile, done once)."""
    payload.user_id = _template_key(user["id"])
    result = _enroll_fused_template(payload)
    signstore.set_enrolled(user["id"])
    return result


# ---------------------------------------------------------------- business

@app.get("/api/v1/business/mine")
def my_business(user: dict = Depends(authmod.require_roles("employer_admin"))):
    biz = signstore.get_business(user["business_id"])
    if not biz:
        raise HTTPException(status_code=404, detail="No business found.")
    return {"business": biz, "employees": signstore.business_employees(biz["id"])}

class RemoveEmployeeIn(BaseModel):
    user_id: int

@app.post("/api/v1/business/employees/remove")
def remove_employee(payload: RemoveEmployeeIn,
                    user: dict = Depends(authmod.require_roles("employer_admin"))):
    if not signstore.remove_employee(payload.user_id, user["business_id"]):
        raise HTTPException(status_code=404, detail="Employee not found in your business.")
    _audit(user["id"], "business.remove_employee",
           f"user_id={payload.user_id}")
    return {"status": "removed"}


# ---------------------------------------------------------------- platform admin

@app.get("/api/v1/admin/overview")
def admin_overview(user: dict = Depends(authmod.require_roles("platform_admin"))):
    return {
        "users_by_role": signstore.count_users_by_role(),
        "businesses": len(signstore.list_businesses()),
        "documents": signstore.count_documents(),
        "signatures": signstore.count_signatures(),
    }

@app.get("/api/v1/admin/businesses")
def admin_businesses(user: dict = Depends(authmod.require_roles("platform_admin"))):
    return signstore.list_businesses()

@app.get("/api/v1/admin/users")
def admin_users(user: dict = Depends(authmod.require_roles("platform_admin"))):
    return signstore.list_users()

@app.get("/api/v1/admin/audit")
def admin_audit(user: dict = Depends(authmod.require_roles("platform_admin")),
                limit: int = 200):
    """Platform admin audit trail: who did what, newest first."""
    return signstore.list_audit(min(max(limit, 1), 500))


# ---------------------------------------------------------------- documents

MAX_PDF_BYTES = 10 * 1024 * 1024

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

@app.post("/api/v1/docs/upload")
async def upload_doc(file: UploadFile = File(...),
                     user: dict = Depends(authmod.get_current_user)):
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF too large (10MB max).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    digest = _sha256(data)
    doc = signstore.create_document(user["id"], user["business_id"],
                                    file.filename or "document.pdf", digest)
    signstore.save_doc_pdf(doc["id"], data)
    _audit(user["id"], "document.upload",
           f"doc_id={doc['id']} filename={doc['filename']}")
    return {"id": doc["id"], "filename": doc["filename"], "sha256": digest,
            "status": doc["status"]}

@app.get("/api/v1/docs")
def list_docs(user: dict = Depends(authmod.get_current_user)):
    return signstore.list_documents_for(user)

@app.get("/api/v1/docs/{doc_id}/download")
def download_doc(doc_id: int, user: dict = Depends(authmod.get_current_user)):
    doc = signstore.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not _can_access_doc(user, doc):
        raise HTTPException(status_code=403, detail="Not your document.")
    data = signstore.load_doc_pdf(doc_id)
    if not data:
        raise HTTPException(status_code=404, detail="File missing.")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="{doc["filename"]}"'})

def _can_access_doc(user: dict, doc: dict) -> bool:
    if user["role"] == "platform_admin":
        return True
    if doc["owner_user_id"] == user["id"]:
        return True
    if user["role"] == "employer_admin" and user["business_id"] \
            and doc["business_id"] == user["business_id"]:
        return True
    # Employees only touch documents assigned to them, never the whole
    # business inbox.
    if user["role"] == "employee" \
            and doc.get("assignee_user_id") == user["id"]:
        return True
    return False


@app.delete("/api/v1/docs/{doc_id}")
def delete_doc(doc_id: int, user: dict = Depends(authmod.get_current_user)):
    doc = signstore.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not _can_access_doc(user, doc):
        raise HTTPException(status_code=403, detail="Not your document.")
    # Deleting is destructive: only the owner, the owning business's admin,
    # or the platform admin may do it. Assigned employees may sign, not delete.
    allowed = (
        doc["owner_user_id"] == user["id"]
        or user["role"] == "platform_admin"
        or (user["role"] == "employer_admin" and user["business_id"]
            and doc["business_id"] == user["business_id"])
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Only the document owner can delete it.")
    result = signstore.delete_document(doc_id)
    _audit(user["id"], "document.delete",
           f"doc_id={doc_id} filename={doc['filename']}")
    return {"status": "deleted", **result}


def _audit(actor_id, action: str, detail: str = ""):
    try:
        signstore.log_audit(actor_id, action, detail)
    except Exception:
        pass  # audit must never break the request it records


class AssignIn(BaseModel):
    user_id: int

@app.post("/api/v1/docs/{doc_id}/assign")
def assign_doc(doc_id: int, payload: AssignIn,
               user: dict = Depends(authmod.require_roles("employer_admin"))):
    doc = signstore.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not user["business_id"] or doc["business_id"] != user["business_id"]:
        raise HTTPException(status_code=403, detail="Not your business's document.")
    if not signstore.assign_document(doc_id, payload.user_id, user["business_id"]):
        raise HTTPException(status_code=400,
                            detail="Assignee must be an employee of your business.")
    _audit(user["id"], "document.assign",
           f"doc_id={doc_id} assignee={payload.user_id}")
    return {"status": "assigned", "doc_id": doc_id, "assignee_user_id": payload.user_id}


# ---------------------------------------------------------------- signing

class SignIn(BaseModel):
    doc_id: int
    points: List[Tuple[float, float]]
    kinematics: List[List[float]] = []
    include_visible_signature: bool = True
    method: str = "air"  # "air" = biometric verification, "draw" = mouse/touch fallback

@app.post("/api/v1/sign")
def sign_document(payload: SignIn, user: dict = Depends(authmod.get_current_user)):
    doc = signstore.get_document(payload.doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not _can_access_doc(user, doc):
        raise HTTPException(status_code=403, detail="Not your document.")
    if doc["status"] == "signed":
        raise HTTPException(status_code=400, detail="Document is already signed.")

    method = payload.method if payload.method in ("air", "draw") else "air"
    margin = None

    if method == "air":
        # One biometric verification against the enrolled profile
        try:
            stored = vault.load_fused_template(_template_key(user["id"]))
        except LookupError:
            raise HTTPException(status_code=400,
                                detail="No air signature enrolled. Enroll once in your profile first, or use the Draw tab.")
        try:
            is_auth, _, _, _, margin = match_against_fused_template(
                payload.points, payload.kinematics, stored, threshold=config.THRESHOLD)
        except Exception as err:
            raise HTTPException(status_code=400, detail=str(err))
        if not is_auth:
            raise HTTPException(status_code=401,
                                detail=f"Signature did not match your enrolled profile (margin {margin}). Try again slower, or use the Draw tab.")
    # method == "draw": the signer is already authenticated by login;
    # no biometric claim is made. Document integrity guarantees still hold.

    original = signstore.load_doc_pdf(doc["id"])
    if not original:
        raise HTTPException(status_code=404, detail="Original file missing.")
    digest = _sha256(original)
    signed_at = pdfsign.utcnow_iso()
    with signstore.get_conn() as conn:
        code = signstore.new_verify_code(conn)

    biz = signstore.get_business(user["business_id"]) if user["business_id"] else None
    stamped = pdfsign.stamp_pdf(
        original, code=code, signer_name=user["name"],
        business_name=biz["name"] if biz else None,
        signed_at=signed_at, doc_hash=digest,
        gesture_points=payload.points if payload.include_visible_signature else None,
    )
    signstore.save_signed_pdf(code, stamped)
    stamped_digest = _sha256(stamped)
    signstore.create_signature(code, doc["id"], user["id"], user["business_id"],
                               digest, payload.include_visible_signature,
                               stamped_sha256=stamped_digest, method=method)
    signstore.mark_signed(doc["id"])
    _audit(user["id"], "document.sign",
           f"doc_id={doc['id']} code={code} method={method}")
    return {"status": "signed", "code": code, "margin": margin, "method": method,
            "download": f"/api/v1/sign/{code}/download"}

@app.get("/api/v1/sign/{code}/download")
def download_signed(code: str, user: dict = Depends(authmod.get_current_user)):
    sig = signstore.get_signature_by_code(code)
    if not sig:
        raise HTTPException(status_code=404, detail="Unknown verification code.")
    doc = signstore.get_document(sig["document_id"])
    if not _can_access_doc(user, doc):
        raise HTTPException(status_code=403, detail="Not your document.")
    data = signstore.load_signed_pdf(code)
    if not data:
        raise HTTPException(status_code=404, detail="Signed file missing.")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="signed-{code}.pdf"'})

@app.get("/api/v1/sign/mine")
def my_signatures(user: dict = Depends(authmod.get_current_user)):
    return signstore.list_signatures_for(user)


# ---------------------------------------------------------------- public verification

@app.get("/api/v1/verify/{code}")
def verify_code(code: str):
    sig = signstore.get_signature_by_code(code)
    if not sig:
        raise HTTPException(status_code=404, detail="Unknown verification code.")
    signer = signstore.get_user(sig["signer_user_id"])
    biz = signstore.get_business(sig["business_id"]) if sig["business_id"] else None
    doc = signstore.get_document(sig["document_id"])
    return {
        "code": sig["code"],
        "verified": True,
        "signer_name": signer["name"] if signer else "?",
        "business_name": biz["name"] if biz else None,
        "filename": doc["filename"] if doc else "?",
        "signed_at": sig["created_at"],
        "doc_sha256": sig["doc_sha256"],
        "stamped_sha256": sig["stamped_sha256"],
        "method": sig.get("method") or "air",
    }

@app.post("/api/v1/verify/{code}/check")
async def verify_file(code: str, file: UploadFile = File(...)):
    sig = signstore.get_signature_by_code(code)
    if not sig:
        raise HTTPException(status_code=404, detail="Unknown verification code.")
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF too large (10MB max).")
    digest = _sha256(data)
    # The stamped PDF anyone downloads carries the seal, so its bytes differ
    # from the original upload. Both are legitimate verification targets.
    if sig["stamped_sha256"] and digest == sig["stamped_sha256"]:
        return {"code": code, "match": True,
                "detail": "This is the stamped signed PDF. It matches the seal "
                          "issued under this code."}
    if digest == sig["doc_sha256"]:
        return {"code": code, "match": True,
                "detail": "This is the exact original file that was signed under "
                          "this code."}
    return {"code": code, "match": False,
            "detail": "File differs from both the signed original and the "
                      "stamped PDF."}
