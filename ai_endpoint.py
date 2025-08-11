# ai_endpoint.py
import os, re, tempfile
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from ai_schema import Invoice, Party, ServiceLine, Totals, run_basic_validation

router = APIRouter(prefix="/ai", tags=["AI"])

# --- Text extraction helpers ---
def _extract_text_pypdf2(path: str) -> str:
    try:
        import PyPDF2  # type: ignore
        text = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text.append(page.extract_text() or "")
        return "\n".join(text).strip()
    except Exception:
        return ""

def _extract_text_pdfminer(path: str) -> str:
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        return (extract_text(path) or "").strip()
    except Exception:
        return ""

def extract_text_from_pdf(path: str) -> str:
    text = _extract_text_pypdf2(path)
    if not text:
        text = _extract_text_pdfminer(path)
    return text

# --- Parsers ---
DATE_PATTERNS = [
    r"\b(\d{2}\.\d{2}\.\d{4})\b",      # 31.12.2025
    r"\b(\d{4}-\d{2}-\d{2})\b",        # 2025-12-31
    r"\b(\d{2}/\d{2}/\d{4})\b",        # 31/12/2025
]
CUR_CODES = ["EUR", "USD", "BGN", "GBP", "RON", "PLN", "HUF", "TRY", "ILS"]

def parse_rule_based(text: str) -> Dict[str, Any]:
    # Currency
    cur = None
    for c in CUR_CODES:
        if re.search(rf"\b{c}\b", text, re.IGNORECASE):
            cur = c
            break
    if not cur:
        if "€" in text: cur = "EUR"
        elif "$" in text: cur = "USD"
        elif "лв" in text.lower(): cur = "BGN"
        else: cur = "EUR"

    # Issue date
    found_date = None
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            raw = m.group(1)
            for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    found_date = datetime.strptime(raw, fmt).date()
                    break
                except Exception:
                    pass
            if found_date:
                break
    if not found_date:
        found_date = datetime.utcnow().date()

    # Invoice number
    inv_no = ""
    m = re.search(r"(Фактура|Ф-ра|Invoice|Inv\.?|№|No\.?)\s*[:#]?\s*([A-Za-z0-9\-\/\.]+)", text, re.IGNORECASE)
    if m:
        inv_no = m.group(2)[:64]

    # VAT percent (best-effort)
    vat_percent = 0.0
    m = re.search(r"(ДДС|VAT)[^\d%]{0,8}(\d{1,2}(?:\.\d{1,2})?)\s*%", text, re.IGNORECASE)
    if m:
        try:
            vat_percent = float(m.group(2))
        except Exception:
            vat_percent = 0.0

    # Totals (best-effort)
    # Try “Общо за плащане” or “Total”
    grand = None
    m = re.search(r"(Общо за плащане|Total)\D{0,10}([0-9][0-9\.\s,]*)", text, re.IGNORECASE)
    if m:
        num = re.sub(r"[^\d,\.]", "", m.group(2))
        num = num.replace(" ", "")
        num = num.replace(",", ".")
        try:
            grand = float(num)
        except Exception:
            grand = None

    # Build minimal result (no service lines by default)
    totals = {
        "subtotal": 0.0,
        "tax_total": 0.0,
        "grand_total": float(grand) if grand is not None else 0.0,
        "currency": cur,
    }

    return {
        "supplier": {"name": ""},   # left empty for now
        "recipient": {"name": ""},
        "invoice_number": inv_no,
        "issue_date": found_date.isoformat(),
        "due_date": None,
        "currency": cur,
        "payment_terms": None,
        "po_number": None,
        "deal_id": None,
        "service_lines": [],        # optional to fill later
        "totals": totals,
        "extractor": "rule",
        "extraction_confidence": 0.35 if inv_no else 0.25,
    }

def parse_with_openai(text: str) -> Dict[str, Any]:
    """
    Optional OpenAI-based parser. If OPENAI_API_KEY not set or library not present,
    raises RuntimeError so caller can fallback to rule-based.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    try:
        # Lazy import to avoid hard dependency if not used
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError("openai package not installed in this environment") from e

    client = OpenAI(api_key=api_key)

    system = (
        "You are an expert invoice parser for Bulgarian/English invoices. "
        "Return ONLY valid JSON matching fields of the provided schema: "
        "supplier{name,vat_id,address,country,iban,swift_bic,email}, "
        "recipient{...}, invoice_number, issue_date(YYYY-MM-DD), due_date, currency, "
        "payment_terms, po_number, deal_id, "
        "service_lines[description,quantity,unit_price,currency,tax_rate,tax_amount,line_total], "
        "totals{subtotal,tax_total,grand_total,currency}, extractor, extraction_confidence."
    )
    user = "Extract an Invoice object from the text below. If unknown, omit or set sensible default.\n\nTEXT:\n" + text[:15000]

    # Use Responses API with json_object format if available; otherwise basic chat with json guard.
    try:
        resp = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            temperature=0.2,
            system=system,
            input=[{"role":"user","content":[{"type":"text","text":user}]}],
            response_format={"type":"json_object"},
        )
        content = resp.output_text  # SDK provides parsed JSON text
    except Exception as e:
        raise RuntimeError(f"OpenAI call failed: {e}")

    import json
    try:
        data = json.loads(content)
    except Exception:
        raise RuntimeError("OpenAI did not return valid JSON")

    data["extractor"] = "ai"
    if "extraction_confidence" not in data:
        data["extraction_confidence"] = 0.7
    return data

@router.post("/parse", response_model=Invoice)
async def parse_invoice(file: UploadFile = File(...)):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(400, "Only PDF files are supported")

    # Save temp PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        text = extract_text_from_pdf(tmp_path)
        if not text:
            raise HTTPException(422, "Could not extract text from PDF")

        # Try AI first; on failure fallback to rules
        payload: Dict[str, Any]
        try:
            payload = parse_with_openai(text)
        except Exception:
            payload = parse_rule_based(text)

        # Ensure required blocks
        payload.setdefault("supplier", {"name": ""})
        payload.setdefault("recipient", {"name": ""})
        payload.setdefault("service_lines", [])
        payload.setdefault("totals", {"subtotal": 0.0, "tax_total": 0.0, "grand_total": 0.0, "currency": payload.get("currency", "EUR")})
        payload.setdefault("currency", payload.get("totals", {}).get("currency", "EUR"))
        payload["source_file"] = file.filename

        model = Invoice(**payload)
        errs, warns = run_basic_validation(model)
        model.validation_errors = errs
        model.validation_warnings = warns

        # If rule-based and we found some key fields, bump confidence a little
        if payload.get("extractor") == "rule":
            filled = sum(1 for v in [model.invoice_number, model.issue_date, model.currency] if v)
            model.extraction_confidence = min(0.6, 0.25 + 0.15 * filled)

        return model

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
