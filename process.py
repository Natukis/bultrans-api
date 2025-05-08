
import os
import re
import datetime
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from fastapi import UploadFile
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
import traceback

SUPPLIERS_PATH = "suppliers.xlsx"
UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def extract_recipient_info(text):
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    recipient = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": ""
    }
    
    for i, line in enumerate(lines):
        if "ID No" in line and i + 1 < len(lines) and "VAT No" in lines[i+1] and i >= 1:
            recipient["RecipientName"] = lines[i - 1]
            id_match = re.search(r"ID No[:\s]*(\d+)", line)
            vat_match = re.search(r"VAT No[:\s]*(\w+)", lines[i + 1])
            recipient["RecipientID"] = id_match.group(1) if id_match else ""
            recipient["RecipientVAT"] = vat_match.group(1) if vat_match else ""
            if i + 2 < len(lines):
                recipient["RecipientAddress"] = lines[i + 2]
            if i + 3 < len(lines):
                recipient["RecipientCity"] = lines[i + 3]
            break

    if not recipient["RecipientCity"]:
        city_match = re.search(r"\b(Sofia|Varna|Plovdiv|Burgas|Ruse)\b", text, re.IGNORECASE)
        if city_match:
            recipient["RecipientCity"] = city_match.group(1)

    return recipient

def number_to_bulgarian_words(amount):
    units = ["", "един", "два", "три", "четири", "пет", "шест", "седем", "осем", "девет"]
    teens = ["десет", "единадесет", "дванадесет", "тринадесет", "четиринадесет", "петнадесет",
             "шестнадесет", "седемнадесет", "осемнадесет", "деветнадесет"]
    tens = ["", "", "двадесет", "тридесет", "четиридесет", "петдесет",
            "шестдесет", "седемдесет", "осемдесет", "деветдесет"]
    hundreds = ["", "сто", "двеста", "триста", "четиристотин", "петстотин",
                "шестстотин", "седемстотин", "осемстотин", "деветстотин"]
    thousands = ["", "хиляда", "две хиляди", "три хиляди", "четири хиляди"]

    def convert_hundreds(n):
        if n == 0:
            return ""
        parts = []
        h = n // 100
        t = (n % 100) // 10
        u = n % 10
        if h:
            parts.append(hundreds[h])
        if t == 1:
            parts.append(teens[u])
        else:
            if t:
                parts.append(tens[t])
            if u:
                parts.append(units[u])
        return " ".join(parts)

    leva = int(amount)
    stotinki = int(round((amount - leva) * 100))

    parts = []

    if leva == 0:
        parts.append("нула лева")
    else:
        if leva >= 1000:
            t = leva // 1000
            parts.append(thousands[t] if t < 5 else units[t] + " хиляди")
            leva = leva % 1000
        parts.append(convert_hundreds(leva))
        parts.append("лева")

    if stotinki > 0:
        parts.append("и")
        parts.append(convert_hundreds(stotinki))
        parts.append("стотинки")

    return " ".join([word for word in parts if word])

def extract_field(pattern, text, default=""):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default

def get_exchange_rate_fallback(date_str, currency):
    return 1.0 if currency == "BGN" else 1.95583

def get_exchange_rate_bnb(date: str, currency: str) -> float:
    try:
        url = "https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?download=xml"
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            raise Exception("BNB fetch failed")

        root = ET.fromstring(response.content)
        for record in root.findall('ROW'):
            date_tag = record.find('DATE')
            if date_tag is None:
                continue
            record_date = date_tag.text.strip()
            code = record.find('CODE').text.strip()
            rate = record.find('RATE').text.strip()
            if record_date == date and code == currency:
                return float(rate.replace(",", "."))
        raise Exception("Rate not found in XML")

    except Exception as e:
        print("⚠️ BNB ERROR:", traceback.format_exc())
        return get_exchange_rate_fallback(date, currency)

async def process_invoice_upload(supplier_id: int, file: UploadFile, template: UploadFile):
    try:
        invoice_path = os.path.join(UPLOAD_DIR, file.filename)
        template_path = os.path.join(UPLOAD_DIR, template.filename)

        with open(invoice_path, "wb") as f:
            f.write(await file.read())
        with open(template_path, "wb") as f:
            f.write(await template.read())

        reader = PdfReader(invoice_path)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

        suppliers = pd.read_excel(SUPPLIERS_PATH)
        required_columns = ["SupplierCompanyID", "Last invoice number", "IBAN", "Bankname", "BankCode",
                            "SupplierName", "SupplierCompanyVAT", "SupplierCity", "SupplierAddress", "SupplierContactPerson"]
        missing_cols = set(required_columns) - set(suppliers.columns)
        if missing_cols:
            raise ValueError(f"Missing columns in suppliers file: {missing_cols}")

        row = suppliers[suppliers["SupplierCompanyID"] == supplier_id]
        if row.empty:
            raise ValueError("Supplier not found")

        invoice_number = str(int(row["Last invoice number"].values[0]) + 1).zfill(10)

        invoice_date_raw = extract_field(r"Date:\s*([\d/\.]+)", text)
        if not invoice_date_raw:
            raise ValueError("Date not found in invoice text")
        invoice_date = invoice_date_raw.replace("/", ".")
        invoice_date_bnb = datetime.datetime.strptime(invoice_date, "%d.%m.%Y").strftime("%Y-%m-%d")

        match = re.search(r"(?i)Total:\s*([A-Z]{3})\s*([\d\.,]+)", text)
        currency, amount = (match.group(1), float(match.group(2).replace(",", ""))) if match else ("BGN", 0)

        exchange_rate = get_exchange_rate_bnb(invoice_date_bnb, currency)
        amount_bgn = round(amount * exchange_rate, 2)

        vat_match = re.search(r"VAT\s+(\d+)%:\s*([\d\.,]+)", text)
        if vat_match:
            vat_amount = float(vat_match.group(2).replace(",", ""))
            total_bgn = amount_bgn + vat_amount
        else:
            vat_amount = None
            total_bgn = amount_bgn

        total_in_words = number_to_bulgarian_words(total_bgn).capitalize()

        recipient = extract_recipient_info(text)

        data = {
            "InvoiceNumber": invoice_number,
            "Date": invoice_date,
            "Amount": amount,
            "Currency": currency,
            "ExchangeRate": exchange_rate,
            "AmountBGN": amount_bgn,
            "VATAmount": vat_amount if vat_amount else "",
            "TotalBGN": total_bgn,
            "TotalInWords": total_in_words,
            "TransactionCountry": "България",
            "TransactionBasis": "По сметка",
            "IBAN": row["IBAN"].values[0],
            "BankName": row["Bankname"].values[0],
            "BankCode": row["BankCode"].values[0],
            "SupplierName": row["SupplierName"].values[0],
            "SupplierCompanyVAT": row["SupplierCompanyVAT"].values[0],
            "SupplierCompanyID": row["SupplierCompanyID"].values[0],
            "SupplierCity": row["SupplierCity"].values[0],
            "SupplierAddress": row["SupplierAddress"].values[0],
            "SupplierContactPerson": row["SupplierContactPerson"].values[0],
            "CompiledBy": row["SupplierContactPerson"].values[0],
            "Month": datetime.datetime.now().strftime("%B"),
            "Year": datetime.datetime.now().year
        }

        data.update(recipient)

        save_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
        doc = DocxTemplate(template_path)
        doc.render(data)
        doc.save(save_path)

        return JSONResponse(content={"success": True, "invoice_number": invoice_number, "file_path": save_path})
    except Exception as e:
        print("❌ INTERNAL ERROR:", traceback.format_exc())
        return JSONResponse(content={"success": False, "error": str(e)})
