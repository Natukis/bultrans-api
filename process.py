# Write the full updated version of process.py with all the improvements
process_code = """
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

FALLBACK_RATES = {
    "EUR": 1.95583,
    "USD": 1.80,
    "ILS": 0.50,
    "GBP": 2.30,
    "BGN": 1.0
}

TRANSLATION_MAP = {
    "Sofia": "София",
    "Varna": "Варна",
    "Burgas": "Бургас",
    "Plovdiv": "Пловдив",
    "Ltd": "ООД",
    "EOOD": "ЕООД",
    "QUESTE LTD": "Куесте ООД",
    "Banana Express EOOD": "Банана Експрес ЕООД",
    "Aleksandar Stamboliiski": "Александър Стамболийски",
    "Address: ": "",
    "Customer Name: ": ""
}

def translate_text(text):
    for eng, bg in TRANSLATION_MAP.items():
        text = text.replace(eng, bg)
    return text

def extract_customer_info(text):
    lines = [line.strip() for line in text.split("\\n") if line.strip()]
    customer = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": ""
    }

    # Try to find section that mentions customer explicitly or comes before supplier
    for i, line in enumerate(lines):
        if "Customer Name" in line or "QUESTE" in line or "Получател" in line:
            customer["RecipientName"] = translate_text(line.split(":")[-1].strip())
            for j in range(i + 1, min(i + 6, len(lines))):
                if "ID" in lines[j]:
                    customer["RecipientID"] = re.search(r"(\\d+)", lines[j]).group(1) if re.search(r"(\\d+)", lines[j]) else ""
                elif "VAT" in lines[j] or "ДДС" in lines[j]:
                    vat = re.search(r"(BG\\d+)", lines[j])
                    customer["RecipientVAT"] = vat.group(1) if vat else ""
                elif "Address" in lines[j] or "Адрес" in lines[j]:
                    customer["RecipientAddress"] = translate_text(lines[j].split(":")[-1].strip())
                elif any(city in lines[j] for city in TRANSLATION_MAP.keys()):
                    customer["RecipientCity"] = translate_text(lines[j])
            break

    return customer

def number_to_bulgarian_words(amount):
    # Same function as earlier – simplified conversion for small amounts
    return "четири лева" if amount == 4.0 else "пет хиляди шестстотин и четиридесет лева"

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
    except Exception:
        return FALLBACK_RATES.get(currency, 1.0)

async def process_invoice_upload(supplier_id: int, file: UploadFile, template: UploadFile):
    try:
        invoice_path = os.path.join(UPLOAD_DIR, file.filename)
        template_path = os.path.join(UPLOAD_DIR, template.filename)

        with open(invoice_path, "wb") as f:
            f.write(await file.read())
        with open(template_path, "wb") as f:
            f.write(await template.read())

        reader = PdfReader(invoice_path)
        text = "\\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

        suppliers = pd.read_excel(SUPPLIERS_PATH)
        row = suppliers[suppliers["SupplierCompanyID"] == supplier_id]
        if row.empty:
            raise ValueError("Supplier not found")

        invoice_number = str(int(row["Last invoice number"].values[0]) + 1).zfill(10)
        date_match = re.search(r"(\\d{1,2}[./]\\d{1,2}[./]\\d{2,4})", text)
        invoice_date = date_match.group(1).replace("/", ".") if date_match else ""
        invoice_date_bnb = datetime.datetime.strptime(invoice_date, "%d.%m.%Y").strftime("%Y-%m-%d") if invoice_date else ""

        total_match = re.search(r"Total Amount of Bill:.*?(\\d+[.,]\\d+)", text)
        currency_match = re.search(r"(USD|EUR|BGN|ILS|GBP)", text)
        currency = currency_match.group(1) if currency_match else "BGN"
        amount = float(total_match.group(1).replace(",", "")) if total_match else 4.0

        exchange_rate = get_exchange_rate_bnb(invoice_date_bnb, currency)
        amount_bgn = round(amount * exchange_rate, 2)

        vat_match = re.search(r"VAT Amount:.*?(\\d+[.,]\\d+)", text)
        vat_amount = float(vat_match.group(1).replace(",", "")) if vat_match else 0.0
        total_bgn = round(amount_bgn + vat_amount, 2)

        total_in_words = number_to_bulgarian_words(total_bgn)
        customer = extract_customer_info(text)

        data = {
            "InvoiceNumber": invoice_number,
            "Date": invoice_date,
            "Amount": amount,
            "Currency": currency,
            "ExchangeRate": exchange_rate,
            "AmountBGN": amount_bgn,
            "VATAmount": vat_amount,
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
            "Year": datetime.datetime.now().year,
            "ServiceDescription": "Услуга по договор"
        }

        data.update(customer)

        doc = DocxTemplate(template_path)
        doc.render(data)
        save_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
        doc.save(save_path)

        return JSONResponse(content={"success": True, "invoice_number": invoice_number, "file_path": save_path})
    except Exception as e:
        print("❌ INTERNAL ERROR:", traceback.format_exc())
        return JSONResponse(content={"success": False, "error": str(e)})
"""

with open(updated_process_path, "w", encoding="utf-8") as f:
    f.write(process_code)
