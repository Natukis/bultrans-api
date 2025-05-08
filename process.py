
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
from num2words import num2words
import traceback

SUPPLIERS_PATH = "suppliers.xlsx"
UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def extract_field(pattern, text, default=""):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default

def get_exchange_rate_fallback(date_str, currency):
    return 1.95583

def get_exchange_rate_bnb(date: str, currency: str) -> float:
    try:
        url = "https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?download=xml"
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            raise Exception("BNB fetch failed")

        root = ET.fromstring(response.content)
        for record in root.findall('ROW'):
            record_date = record.find('DATE').text.strip()
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
        for col in required_columns:
            if col not in suppliers.columns:
                raise ValueError(f"Missing required column in suppliers file: {col}")

        row = suppliers[suppliers["SupplierCompanyID"] == supplier_id]
        if row.empty:
            raise ValueError("Supplier not found")

        invoice_number = str(int(row["Last invoice number"].values[0]) + 1).zfill(10)
        invoice_date = extract_field(r"Date:\s*([\d/\.]+)", text).replace("/", ".")
        invoice_date_bnb = datetime.datetime.strptime(invoice_date, "%d.%m.%Y").strftime("%Y-%m-%d")

        match = re.search(r"Total Amount of Bill:\s*([A-Z]{3})\s*([\d\.,]+)", text)
        currency, amount = (match.group(1), float(match.group(2).replace(",", ""))) if match else ("EUR", 0)

        exchange_rate = get_exchange_rate_bnb(invoice_date_bnb, currency)
        amount_bgn = round(amount * exchange_rate, 2)

        vat_match = re.search(r"VAT\s+(\d+)%:\s*([\d\.,]+)", text)
        if vat_match:
            vat_amount = float(vat_match.group(2).replace(",", ""))
            total_bgn = amount_bgn + vat_amount
        else:
            vat_amount = None
            total_bgn = amount_bgn

        total_in_words = num2words(total_bgn, lang='bg').capitalize()

        data = {
            "InvoiceNumber": invoice_number,
            "Date": invoice_date,
            "CustomerName": extract_field(r"Customer Name:\s*(.+)", text),
            "CustomerVAT": extract_field(r"Customer VAT:\s*(.+)", text),
            "CustomerID": extract_field(r"Customer ID:\s*(.+)", text),
            "CustomerAddress": extract_field(r"Customer Address:\s*(.+)", text),
            "RecipientCity": extract_field(r"Customer City:\s*(.+)", text),
            "ServiceDescription": extract_field(r"Service Description:\s*(.+)", text),
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

        save_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
        doc = DocxTemplate(template_path)
        doc.render(data)
        doc.save(save_path)

        return JSONResponse(content={"success": True, "invoice_number": invoice_number, "file_path": save_path})
    except Exception as e:
        print("❌ INTERNAL ERROR:", traceback.format_exc())
        return JSONResponse(content={"success": False, "error": str(e)})
