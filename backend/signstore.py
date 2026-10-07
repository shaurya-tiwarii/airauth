"""AirAuth service layer: users, businesses, documents, signatures.

SQLite-backed. Biometric templates stay in the separate encrypted vault
(security.py); this DB holds account and document-signing records.
"""
import secrets
import sqlite3
import string
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "airauth.db")
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


def get_conn() -> sqlite3.Connection:
    _init_dirs()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


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
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
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
                include_visible_sig INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def new_invite_code() -> str:
    return "BIZ-" + "".join(secrets.choice(string.ascii_uppercase + string.digits)
                            for _ in range(6))


def new_verify_code(conn: sqlite3.Connection) -> str:
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
    with get_conn() as conn:
        if user["role"] == "platform_admin":
            rows = conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
        elif user["role"] in ("employer_admin", "employee") and user["business_id"]:
            rows = conn.execute(
                "SELECT * FROM documents WHERE business_id = ? OR owner_user_id = ?"
                " ORDER BY id DESC", (user["business_id"], user["id"])).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents WHERE owner_user_id = ? ORDER BY id DESC",
                (user["id"],)).fetchall()
        return [row_to_dict(r) for r in rows]


def mark_signed(did: int):
    with get_conn() as conn:
        conn.execute("UPDATE documents SET status = 'signed' WHERE id = ?", (did,))
        conn.commit()


def doc_path(did: int) -> Path:
    return DOCS_DIR / f"{did}.pdf"


def signed_path(code: str) -> Path:
    return SIGNED_DIR / f"{code}.pdf"


# ---- signatures ----------------------------------------------------------

def create_signature(code: str, document_id: int, signer_id: int,
                     business_id, doc_sha256: str, include_visible_sig: bool) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO signatures
               (code, document_id, signer_user_id, business_id, doc_sha256,
                include_visible_sig, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, document_id, signer_id, business_id, doc_sha256,
             1 if include_visible_sig else 0, utcnow()),
        )
        sid = cur.lastrowid
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM signatures WHERE id = ?", (sid,)).fetchone())


def get_signature_by_code(code: str) -> dict:
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM signatures WHERE code = ?", (code.strip().upper(),)).fetchone())


def list_signatures_for(user: dict) -> list:
    with get_conn() as conn:
        if user["role"] == "platform_admin":
            rows = conn.execute("SELECT * FROM signatures ORDER BY id DESC").fetchall()
        elif user["role"] in ("employer_admin", "employee") and user["business_id"]:
            rows = conn.execute(
                "SELECT * FROM signatures WHERE business_id = ? OR signer_user_id = ?"
                " ORDER BY id DESC", (user["business_id"], user["id"])).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signatures WHERE signer_user_id = ? ORDER BY id DESC",
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
