# ai_schema.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, validator
from datetime import date

class Party(BaseModel):
    name: str = ""
    vat_id: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    iban: Optional[str] = None
    swift_bic: Optional[str] = None
    email: Optional[str] = None

class ServiceLine(BaseModel):
    description: str = "Услуги"
    quantity: float = 1.0
    unit_price: float = 0.0         # price per unit in original currency
    currency: Optional[str] = None  # original currency (EUR/USD/BGN/…)
    tax_rate: float = 0.0           # percent, e.g. 20 for 20%
    tax_amount: Optional[float] = None
    line_total: Optional[float] = None  # with tax, in original currency

    @validator("tax_amount", always=True)
    def _calc_tax_amount(cls, v, values):
        if v is not None:
            return round(v, 2)
        qty = float(values.get("quantity") or 0.0)
        price = float(values.get("unit_price") or 0.0)
        rate = float(values.get("tax_rate") or 0.0)
        return round(qty * price * (rate / 100.0), 2)

    @validator("line_total", always=True)
    def _calc_line_total(cls, v, values):
        if v is not None:
            return round(v, 2)
        qty = float(values.get("quantity") or 0.0)
        price = float(values.get("unit_price") or 0.0)
        tax = float(values.get("tax_amount") or 0.0)
        return round(qty * price + tax, 2)

class Totals(BaseModel):
    subtotal: float = 0.0     # before tax (original currency)
    tax_total: float = 0.0
    grand_total: float = 0.0
    currency: str = "EUR"     # invoice currency

class Invoice(BaseModel):
    source_file: Optional[str] = None

    supplier: Party = Field(default_factory=Party)
    recipient: Party = Field(default_factory=Party)

    invoice_number: str = ""
    issue_date: date
    due_date: Optional[date] = None
    currency: str = "EUR"
    payment_terms: Optional[str] = None
    po_number: Optional[str] = None
    deal_id: Optional[str] = None

    service_lines: List[ServiceLine] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)

    extractor: str = "hybrid"            # "rule" | "ai" | "hybrid"
    extraction_confidence: float = 0.0   # 0..1
    validation_errors: List[str] = Field(default_factory=list)
    validation_warnings: List[str] = Field(default_factory=list)
    template_hint: Optional[str] = None

    @validator("totals")
    def _totals_currency_match(cls, v, values):
        inv_cur = (values.get("currency") or "").upper()
        if (v.currency or "").upper() != inv_cur:
            raise ValueError("Totals.currency must match invoice currency")
        return v

def run_basic_validation(model: Invoice) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not model.invoice_number:
        warnings.append("Missing invoice_number")
    if not model.supplier.name:
        warnings.append("Missing supplier.name")
    if not model.recipient.name:
        warnings.append("Missing recipient.name")

    subtotal = round(sum(round(sl.quantity * sl.unit_price, 2) for sl in model.service_lines), 2)
    tax_total = round(sum(round(sl.tax_amount or 0.0, 2) for sl in model.service_lines), 2)
    grand = round(subtotal + tax_total, 2)

    if round(model.totals.subtotal, 2) != subtotal:
        warnings.append(f"Subtotal mismatch: model={model.totals.subtotal} computed={subtotal}")
    if round(model.totals.tax_total, 2) != tax_total:
        warnings.append(f"Tax total mismatch: model={model.totals.tax_total} computed={tax_total}")
    if round(model.totals.grand_total, 2) != grand:
        errors.append(f"Grand total mismatch: model={model.totals.grand_total} computed={grand}")

    # simple IBAN sanity
    for pfx, party in (("supplier", model.supplier), ("recipient", model.recipient)):
        if party.iban and len(party.iban.replace(" ", "")) < 12:
            warnings.append(f"{pfx}.iban looks too short")

    return errors, warnings
