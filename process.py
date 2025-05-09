
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
    "Address:": "",
    "Customer Name:": "",
    "Services based on agreement": "Услуга по договор"
}

def translate_text(text):
    for eng, bg in TRANSLATION_MAP.items():
        text = text.replace(eng, bg)
    return text

def extract_customer_info(text):
    customer = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": ""
    }
    try:
        customer_name = re.search(r"Customer Name:\s*(.+?)\n", text)
        if customer_name:
            cleaned_name = customer_name.group(1).replace("Supplier", "").strip()
            customer["RecipientName"] = translate_text(cleaned_name)

        id_match = re.search(r"ID No[:]*\s*(\d+)", text)
        if id_match:
            customer["RecipientID"] = id_match.group(1).strip()

        vat_match = re.search(r"VAT No[:]*\s*(BG\d+)", text)
        if vat_match:
            customer["RecipientVAT"] = vat_match.group(1).strip()

        address_match = re.search(r"Address:\s*(.+?)\n", text)
        if address_match:
            address_line = address_match.group(1).strip()
            customer["RecipientAddress"] = translate_text(address_line)

        city_match = re.search(r"\b(Sofia|Varna|Burgas|Plovdiv)\b", text)
        if city_match:
            customer["RecipientCity"] = translate_text(city_match.group(1))
    except Exception:
        pass
    return customer

def number_to_bulgarian_words(amount):
    return num2words(int(amount), lang='bg') + " лева"

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

def extract_invoice_date(text):
    patterns = [
        (r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})", "%d.%m.%Y"),
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"([A-Za-z]{3,9} \d{1,2}, \d{4})", "%B %d %Y"),
        (r"([A-Za-z]{3} \d{1,2}, \d{4})", "%b %d %Y")
    ]
    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                parsed = datetime.datetime.strptime(match.group(1).replace("/", ".").replace(",", ""), fmt)
                return parsed.strftime("%d.%m.%Y"), parsed.strftime("%Y-%m-%d")
            except:
                continue
    return "", ""

def safe_extract_float(segment):
    match = re.findall(r"\d+[.,]?\d*", segment)
    return float(match[0].replace(",", "")) if match else 0.0

async def process_invoice_upload(supplier_id: int, file: UploadFile, template: UploadFile):
    try:
        invoice_path = os.path.join(UPLOAD_DIR, file.filename)
        template_path = os.path.join(UPLOAD_DIR, template.filename)
        with open(invoice_path, "wb") as f:
            f.write(await file.read())
        with open(template_path, "wb") as f:
            f.write(await template.read())

        reader = PdfReader(invoice_path)
        text = "
".join([page.extract_text() for page in reader.pages if page.extract_text()])
        text = text.replace("
", " ")

        suppliers = pd.read_excel(SUPPLIERS_PATH)
        row = suppliers[suppliers["SupplierCompanyID"] == supplier_id]
        if row.empty:
            raise ValueError("Supplier not found")

        invoice_number = str(int(row["Last invoice number"].values[0]) + 1).zfill(10)
        invoice_date, invoice_date_bnb = extract_invoice_date(text)

        total_match = re.search(r"Total Amount:\s*BGN\s*([\d\s,.]+)", text)
        vat_match = re.search(r"VAT Amount:\s*BGN\s*([\d\s,.]+)", text)
        final_match = re.search(r"Total Amount of Bill:\s*BGN\s*([\d\s,.]+)", text)

        amount = safe_extract_float(total_match.group(1)) if total_match else 0.0
        vat_amount = safe_extract_float(vat_match.group(1)) if vat_match else 0.0
        total_bgn = safe_extract_float(final_match.group(1)) if final_match else amount + vat_amount
        total_in_words = number_to_bulgarian_words(total_bgn)

        currency_match = re.search(r"(USD|EUR|BGN|ILS|GBP)", text)
        currency = currency_match.group(1) if currency_match else "BGN"
        exchange_rate = get_exchange_rate_bnb(invoice_date_bnb, currency) if currency != "BGN" else 1.0
        amount_bgn = round(amount * exchange_rate, 2)

        customer = extract_customer_info(text)
        service_desc_match = re.search(r"Services based on agreement from (\d{1,2}[./]\d{1,2}[./]\d{2,4})", text)
        service_description = f"Услуга по договор от {service_desc_match.group(1)}" if service_desc_match else "Услуга по договор"

        supplier_contact = row["SupplierContactPerson"].values[0]
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
            "SupplierName": translate_text(row["SupplierName"].values[0]),
            "SupplierCompanyVAT": row["SupplierCompanyVAT"].values[0],
            "SupplierCompanyID": row["SupplierCompanyID"].values[0],
            "SupplierCity": translate_text(row["SupplierCity"].values[0]),
            "SupplierAddress": translate_text(row["SupplierAddress"].values[0]),
            "SupplierContactPerson": supplier_contact,
            "CompiledBy": supplier_contact,
            "Month": datetime.datetime.now().strftime("%B"),
            "Year": datetime.datetime.now().year,
            "ServiceDescription": service_description
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
