"""PDF stamping for signed documents.

Mandatory on every signed PDF: a light diagonal "VERIFIED BY AIRAUTH"
watermark on each page plus a footer seal with the unique verification
code. Optional: the signer's drawn gesture rendered as an ink signature
on a signature block on the last page.
"""
import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

SEAL_BLUE = HexColor("#1a3a5c")
LIGHT_GRAY = HexColor("#9aa7b4")
INK = HexColor("#14243a")

SHORT_HASH_LEN = 16


def render_gesture_png(points, width: int = 480, height: int = 160) -> bytes:
    """Render raw gesture points as an ink signature PNG."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1e-6
    span_y = (max_y - min_y) or 1e-6
    pad = 18
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    norm = [((x - min_x) * scale + pad, (y - min_y) * scale + pad) for x, y in zip(xs, ys)]

    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.line(norm, fill=(20, 36, 58, 255), width=5, joint="curve")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _overlay_page(page_w: float, page_h: float, code: str, signed_at: str,
                  last_page: bool, sig_png: bytes | None, signer_name: str,
                  business_name: str | None, doc_hash: str) -> io.BytesIO:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    # Diagonal watermark on every page
    c.saveState()
    c.setFillColor(LIGHT_GRAY)
    c.setFont("Helvetica-Bold", 64)
    c.translate(page_w / 2, page_h / 2)
    c.rotate(35)
    c.setFillAlpha(0.10)
    c.drawCentredString(0, 0, "VERIFIED BY AIRAUTH")
    c.restoreState()

    # Footer seal on every page
    c.setFillColor(SEAL_BLUE)
    c.setFont("Helvetica-Bold", 9)
    seal = f"Verified by AirAuth  |  {code}  |  {signed_at[:10]}"
    c.drawRightString(page_w - 36, 30, seal)

    # Signature block on the last page
    if last_page:
        y = 120
        c.setFillColor(SEAL_BLUE)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(48, y + 64, "Signed with AirAuth")
        if sig_png:
            img_buf = io.BytesIO(sig_png)
            c.drawImage(ImageReader(img_buf), 48, y - 30, width=200, height=66,
                        preserveAspectRatio=True, mask="auto")
            name_y = y - 52
        else:
            name_y = y - 8
        c.setFillColor(INK)
        c.setFont("Helvetica", 11)
        c.drawString(48, name_y, f"Signer: {signer_name}")
        if business_name:
            c.drawString(48, name_y - 16, f"Business: {business_name}")
        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#5a6b7c"))
        c.drawString(48, name_y - 32, f"Verification code: {code}")
        c.drawString(48, name_y - 46, f"Document SHA-256: {doc_hash[:SHORT_HASH_LEN]}...")
        c.drawString(48, name_y - 60, f"Signed at: {signed_at}")

    c.save()
    buf.seek(0)
    return buf


def stamp_pdf(original: bytes, code: str, signer_name: str,
              business_name: str | None, signed_at: str, doc_hash: str,
              gesture_points: list | None) -> bytes:
    """Return a new PDF with verification marks stamped over the original."""
    reader = PdfReader(io.BytesIO(original))
    writer = PdfWriter()

    sig_png = render_gesture_png(gesture_points) if gesture_points else None
    n = len(reader.pages)
    for i, page in enumerate(reader.pages):
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        overlay = _overlay_page(w, h, code, signed_at, last_page=(i == n - 1),
                                sig_png=sig_png if i == n - 1 else None,
                                signer_name=signer_name, business_name=business_name,
                                doc_hash=doc_hash)
        overlay_reader = PdfReader(overlay)
        page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
