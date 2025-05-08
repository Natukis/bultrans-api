
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
        row = suppliers[suppliers["SupplierCompanyID"] == supplier_id]
        if row.empty:
            raise ValueError("Supplier not found")

        invoice_date_raw = extract_field(r"Date:\s*([\d/\.]+)", text)
        invoice_date = invoice_date_raw.replace("/", ".")
        invoice_date_bnb = datetime.datetime.strptime(invoice_date, "%d.%m.%Y").strftime("%Y-%m-%d")

        data = {
            "Date": invoice_date
        }

        print("📅 Injecting Date:", data.get("Date"))

        doc = DocxTemplate(template_path)
        doc.render(data)
        save_path = f"/tmp/debug_test.docx"
        doc.save(save_path)

        return JSONResponse(content={"success": True, "file_path": save_path})
    except Exception as e:
        print("❌ INTERNAL ERROR:", traceback.format_exc())
        return JSONResponse(content={"success": False, "error": str(e)})
