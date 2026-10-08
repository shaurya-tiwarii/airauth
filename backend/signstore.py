"""AirAuth service layer: users, businesses, documents, signatures.

Database-backed via db.py (local SQLite for dev, Turso when TURSO_URL and
TURSO_TOKEN are set). Biometric templates stay in the separate encrypted
vault (security.py); this DB holds account and document-signing records.
PDF bytes live in the DB too, so documents survive Render restarts.
"""
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

import db

BASE_DIR = Path(__file__).resolve().parent
# Legacy on-disk PDF locations (pre-Turso). Reads fall back to these;
# all new writes go to the database.
STORAGE_DIR = BASE_DIR / "storage"
DOCS_DIR = STORAGE_DIR / "docs"
SIGNED_DIR = STORAGE_DIR / "signed"

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no confusing chars

ROLES = ("platform_admin", "employer_admin", "employee", "user")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init_dirs():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    SIGNED_DIR.mkdir(parents=True, exist_ok=True)


def get_conn():
    _init_dirs()
    return db.connect()


def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                pw_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                business_id INTEGER,
                airsig_enrolled INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                invite_code TEXT UNIQUE NOT NULL,
                admin_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                business_id INTEGER,
                assignee_user_id INTEGER,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                pdf_data BLOB,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                document_id INTEGER NOT NULL,
                signer_user_id INTEGER NOT NULL,
                business_id INTEGER,
                doc_sha256 TEXT NOT NULL,
                stamped_sha256 TEXT,
                include_visible_sig INTEGER DEFAULT 1,
                stamped_pdf_data BLOB,
                created_at TEXT NOT NULL
            )
        """)
        # Migrations for databases created before these columns existed.
        # Try the ALTER and ignore "duplicate column" errors: this works on
        # both SQLite and Turso without relying on PRAGMA over HTTP.
        for table, column, ctype in (("documents", "assignee_user_id", "INTEGER"),
                                     ("documents", "pdf_data", "BLOB"),
                                     ("signatures", "stamped_sha256", "TEXT"),
                                     ("signatures", "method", "TEXT DEFAULT 'air'"),
                                     ("signatures", "stamped_pdf_data", "BLOB")):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER,
                action TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def new_invite_code() -> str:
    return "BIZ-" + "".join(secrets.choice(string.ascii_uppercase + string.digits)
                            for _ in range(6))


def new_verify_code(conn) -> str:
    while True:
        code = "AA-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        row = conn.execute("SELECT 1 FROM signatures WHERE code = ?", (code,)).fetchone()
        if not row:
            return code


def row_to_dict(row) -> dict:
    return dict(row) if row else None


# ---- users ---------------------------------------------------------------

def create_user(email: str, pw_hash: str, name: str, role: str,
                business_id=None) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO users (email, pw_hash, name, role, business_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (email.lower().strip(), pw_hash, name.strip(), role, business_id, utcnow()),
        )
        uid = cur.lastrowid
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def get_user_by_email(email: str) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone())


def get_user(uid: int) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def set_enrolled(uid: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET airsig_enrolled = 1 WHERE id = ?", (uid,))
        conn.commit()


def set_password(uid: int, pw_hash: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, uid))
        conn.commit()


def list_users() -> list:
    with get_conn() as conn:
        return [row_to_dict(r) for r in
                conn.execute("SELECT id, email, name, role, business_id, airsig_enrolled, created_at"
                            " FROM users ORDER BY id").fetchall()]


def count_users_by_role() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT role, COUNT(*) n FROM users GROUP BY role").fetchall()
        return {r["role"]: r["n"] for r in rows}


# ---- businesses ----------------------------------------------------------

def create_business(name: str, admin_user_id: int) -> dict:
    with get_conn() as conn:
        while True:
            code = new_invite_code()
            if not conn.execute("SELECT 1 FROM businesses WHERE invite_code = ?",
                                (code,)).fetchone():
                break
        cur = conn.execute(
            """INSERT INTO businesses (name, invite_code, admin_user_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (name.strip(), code, admin_user_id, utcnow()),
        )
        bid = cur.lastrowid
        conn.execute("UPDATE users SET business_id = ? WHERE id = ?", (bid, admin_user_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone())


def get_business(bid: int) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone())


def get_business_by_invite(code: str) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM businesses WHERE invite_code = ?", (code.strip().upper(),)).fetchone())


def list_businesses() -> list:
    with get_conn() as conn:
        return [row_to_dict(r) for r in
                conn.execute("SELECT * FROM businesses ORDER BY id").fetchall()]


def business_employees(bid: int) -> list:
    with get_conn() as conn:
        return [row_to_dict(r) for r in conn.execute(
            "SELECT id, email, name, role, airsig_enrolled, created_at FROM users"
            " WHERE business_id = ? ORDER BY id", (bid,)).fetchall()]


def remove_employee(uid: int, bid: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET business_id = NULL WHERE id = ? AND business_id = ?"
            " AND role = 'employee'", (uid, bid))
        conn.commit()
        return cur.rowcount > 0


# ---- documents -----------------------------------------------------------

def create_document(owner_id: int, business_id, filename: str, sha256: str) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO documents (owner_user_id, business_id, filename, sha256, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (owner_id, business_id, filename, sha256, utcnow()),
        )
        did = cur.lastrowid
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone())


def get_document(did: int) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone())


def list_documents_for(user: dict) -> list:
    # Never SELECT * here: documents.pdf_data is a BLOB that must not leak
    # into JSON API responses.
    cols = ("id, filename, sha256, owner_user_id, business_id, assignee_user_id,"
            " status, created_at")
    with get_conn() as conn:
        if user["role"] == "platform_admin":
            rows = conn.execute(f"SELECT {cols} FROM documents ORDER BY id DESC").fetchall()
        elif user["role"] == "employer_admin" and user["business_id"]:
            rows = conn.execute(
                f"SELECT {cols} FROM documents WHERE business_id = ? OR owner_user_id = ?"
                " ORDER BY id DESC", (user["business_id"], user["id"])).fetchall()
        elif user["role"] == "employee" and user["business_id"]:
            # Employees see only their own uploads and documents assigned to them.
            rows = conn.execute(
                f"SELECT {cols} FROM documents WHERE owner_user_id = ? OR assignee_user_id = ?"
                " ORDER BY id DESC", (user["id"], user["id"])).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM documents WHERE owner_user_id = ? ORDER BY id DESC",
                (user["id"],)).fetchall()
        return [row_to_dict(r) for r in rows]


def assign_document(doc_id: int, assignee_id: int, business_id: int) -> bool:
    """Assign a business document to an employee of the same business."""
    with get_conn() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc or doc["business_id"] != business_id:
            return False
        emp = conn.execute("SELECT * FROM users WHERE id = ?", (assignee_id,)).fetchone()
        if not emp or emp["role"] != "employee" or emp["business_id"] != business_id:
            return False
        conn.execute("UPDATE documents SET assignee_user_id = ? WHERE id = ?",
                     (assignee_id, doc_id))
        conn.commit()
        return True


def mark_signed(did: int):
    with get_conn() as conn:
        conn.execute("UPDATE documents SET status = 'signed' WHERE id = ?", (did,))
        conn.commit()


def doc_path(did: int) -> Path:
    """Legacy on-disk location. Reads fall back here; writes go to the DB."""
    return DOCS_DIR / f"{did}.pdf"


def signed_path(code: str) -> Path:
    """Legacy on-disk location. Reads fall back here; writes go to the DB."""
    return SIGNED_DIR / f"{code}.pdf"


def save_doc_pdf(did: int, data: bytes):
    with get_conn() as conn:
        conn.execute("UPDATE documents SET pdf_data = ? WHERE id = ?", (data, did))
        conn.commit()


def load_doc_pdf(did: int) -> bytes | None:
    with get_conn() as conn:
        row = conn.execute("SELECT pdf_data FROM documents WHERE id = ?",
                           (did,)).fetchone()
    if row and row["pdf_data"]:
        return bytes(row["pdf_data"])
    # Fallback for PDFs saved before the database migration.
    path = doc_path(did)
    return path.read_bytes() if path.exists() else None


def save_signed_pdf(code: str, data: bytes):
    with get_conn() as conn:
        conn.execute("UPDATE signatures SET stamped_pdf_data = ? WHERE code = ?",
                     (data, code))
        conn.commit()


def load_signed_pdf(code: str) -> bytes | None:
    with get_conn() as conn:
        row = conn.execute("SELECT stamped_pdf_data FROM signatures WHERE code = ?",
                           (code,)).fetchone()
    if row and row["stamped_pdf_data"]:
        return bytes(row["stamped_pdf_data"])
    path = signed_path(code)
    return path.read_bytes() if path.exists() else None


def delete_document(did: int) -> dict:
    """Delete a document, its original PDF, and any signatures (and stamped
    PDFs) made on it. Returns the list of verification codes that were
    retired with it."""
    with get_conn() as conn:
        codes = [r["code"] for r in conn.execute(
            "SELECT code FROM signatures WHERE document_id = ?", (did,))]
        conn.execute("DELETE FROM signatures WHERE document_id = ?", (did,))
        conn.execute("DELETE FROM documents WHERE id = ?", (did,))
        conn.commit()
    try:
        doc_path(did).unlink(missing_ok=True)
    except OSError:
        pass
    for code in codes:
        try:
            signed_path(code).unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted_document_id": did, "retired_codes": codes}


# ---- audit ----------------------------------------------------------

def log_audit(actor_user_id, action: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor_user_id, action, detail, created_at)"
            " VALUES (?, ?, ?, ?)",
            (actor_user_id, action, detail or "", utcnow()),
        )
        conn.commit()


def list_audit(limit: int = 200) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.*, u.email AS actor_email, u.name AS actor_name"
            " FROM audit_log a LEFT JOIN users u ON u.id = a.actor_user_id"
            " ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
        return [row_to_dict(r) for r in rows]


# ---- signatures ----------------------------------------------------------

def create_signature(code: str, document_id: int, signer_id: int,
                     business_id, doc_sha256: str, include_visible_sig: bool,
                     stamped_sha256: str = None, method: str = "air") -> dict:
    if method not in ("air", "draw"):
        method = "air"
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO signatures
               (code, document_id, signer_user_id, business_id, doc_sha256,
                stamped_sha256, include_visible_sig, method, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, document_id, signer_id, business_id, doc_sha256,
             stamped_sha256, 1 if include_visible_sig else 0, method, utcnow()),
        )
        sid = cur.lastrowid
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM signatures WHERE id = ?", (sid,)).fetchone())


def get_signature_by_code(code: str) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM signatures WHERE code = ?", (code.strip().upper(),)).fetchone())


def list_signatures_for(user: dict) -> list:
    # Never SELECT * here: signatures.stamped_pdf_data is a BLOB that must
    # not leak into JSON API responses.
    cols = ("id, code, document_id, signer_user_id, business_id, doc_sha256,"
            " include_visible_sig, stamped_sha256, method, created_at")
    with get_conn() as conn:
        if user["role"] == "platform_admin":
            rows = conn.execute(f"SELECT {cols} FROM signatures ORDER BY id DESC").fetchall()
        elif user["role"] == "employer_admin" and user["business_id"]:
            rows = conn.execute(
                f"SELECT {cols} FROM signatures WHERE business_id = ? OR signer_user_id = ?"
                " ORDER BY id DESC", (user["business_id"], user["id"])).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM signatures WHERE signer_user_id = ? ORDER BY id DESC",
                (user["id"],)).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r)
            doc = row_to_dict(conn.execute(
                "SELECT filename FROM documents WHERE id = ?", (d["document_id"],)).fetchone())
            signer = row_to_dict(conn.execute(
                "SELECT name, email FROM users WHERE id = ?", (d["signer_user_id"],)).fetchone())
            biz = row_to_dict(conn.execute(
                "SELECT name FROM businesses WHERE id = ?", (d["business_id"],)).fetchone()) \
                if d["business_id"] else None
            d["filename"] = doc["filename"] if doc else "?"
            d["signer_name"] = signer["name"] if signer else "?"
            d["signer_email"] = signer["email"] if signer else "?"
            d["business_name"] = biz["name"] if biz else None
            out.append(d)
        return out


def count_signatures() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) n FROM signatures").fetchone()["n"]


def count_documents() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) n FROM documents").fetchone()["n"]
