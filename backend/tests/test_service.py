"""Tests for the AirAuth document-signing service layer."""
import hashlib
import io
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth as authmod
import pdfsign
import signstore


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(signstore, "DB_FILE", str(tmp_path / "t.db"))
    monkeypatch.setattr(signstore, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(signstore, "DOCS_DIR", tmp_path / "storage" / "docs")
    monkeypatch.setattr(signstore, "SIGNED_DIR", tmp_path / "storage" / "signed")
    signstore.init_db()
    return tmp_path


def test_password_roundtrip():
    h = authmod.hash_password("correct-horse-123")
    assert authmod.check_password("correct-horse-123", h)
    assert not authmod.check_password("wrong", h)


def test_password_too_short():
    with pytest.raises(ValueError):
        authmod.hash_password("short")


def test_jwt_roundtrip():
    tok = authmod.make_token(42, "employee")
    payload = authmod.decode_token(tok)
    assert payload["sub"] == "42" and payload["role"] == "employee"


def test_jwt_tampered_rejected():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        authmod.decode_token("garbage.token.here")


def test_register_business_flow(db):
    admin = signstore.create_user("boss@co.com", authmod.hash_password("password123"),
                                  "Boss", "employer_admin")
    biz = signstore.create_business("Acme", admin["id"])
    assert biz["invite_code"].startswith("BIZ-")
    emp = signstore.create_user("e@co.com", authmod.hash_password("password123"),
                                "Emp", "employee", business_id=biz["id"])
    emps = signstore.business_employees(biz["id"])
    assert {e["email"] for e in emps} == {"boss@co.com", "e@co.com"}
    assert signstore.remove_employee(emp["id"], biz["id"])
    assert signstore.get_user(emp["id"])["business_id"] is None


def test_invite_lookup(db):
    admin = signstore.create_user("b@co.com", authmod.hash_password("password123"),
                                  "B", "employer_admin")
    biz = signstore.create_business("Acme", admin["id"])
    found = signstore.get_business_by_invite(biz["invite_code"].lower())
    assert found["id"] == biz["id"]
    assert signstore.get_business_by_invite("BIZ-NOPE") is None


def test_verify_codes_unique(db):
    with signstore.get_conn() as conn:
        codes = {signstore.new_verify_code(conn) for _ in range(50)}
    assert len(codes) == 50
    assert all(c.startswith("AA-") and len(c) == 11 for c in codes)


def _minimal_pdf() -> bytes:
    from reportlab.pdfgen import canvas as rc
    buf = io.BytesIO()
    c = rc.Canvas(buf, pagesize=(595, 842))
    c.drawString(100, 700, "Test contract")
    c.showPage()
    c.drawString(100, 700, "Page two")
    c.save()
    return buf.getvalue()


def test_stamp_pdf_valid_and_marked():
    original = _minimal_pdf()
    digest = hashlib.sha256(original).hexdigest()
    pts = [[i / 40, 0.5 + 0.1 * np.sin(i / 5)] for i in range(40)]
    stamped = pdfsign.stamp_pdf(original, code="AA-TEST1234", signer_name="Alice",
                                business_name="Acme", signed_at="2026-10-07T00:00:00+00:00",
                                doc_hash=digest, gesture_points=pts)
    assert stamped.startswith(b"%PDF")
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(stamped))
    assert len(reader.pages) == 2
    text = "".join((p.extract_text() or "") for p in reader.pages)
    assert "AA-TEST1234" in text
    assert "Verified by AirAuth" in text


def test_stamp_pdf_without_visible_signature():
    original = _minimal_pdf()
    stamped = pdfsign.stamp_pdf(original, code="AA-NOSIG01", signer_name="Bob",
                                business_name=None, signed_at="2026-10-07T00:00:00+00:00",
                                doc_hash="ab" * 32, gesture_points=None)
    assert stamped.startswith(b"%PDF")


def test_render_gesture_png():
    pts = [[i / 40, 0.3] for i in range(40)]
    png = pdfsign.render_gesture_png(pts)
    assert png.startswith(b"\x89PNG")


def test_signature_record_flow(db):
    u = signstore.create_user("s@co.com", authmod.hash_password("password123"),
                              "Signer", "user")
    doc = signstore.create_document(u["id"], None, "contract.pdf", "ff" * 32)
    with signstore.get_conn() as conn:
        code = signstore.new_verify_code(conn)
    signstore.create_signature(code, doc["id"], u["id"], None, "ff" * 32, True)
    signstore.mark_signed(doc["id"])
    assert signstore.get_document(doc["id"])["status"] == "signed"
    sig = signstore.get_signature_by_code(code.lower())
    assert sig["document_id"] == doc["id"]
    mine = signstore.list_signatures_for(signstore.get_user(u["id"]))
    assert len(mine) == 1 and mine[0]["filename"] == "contract.pdf"
