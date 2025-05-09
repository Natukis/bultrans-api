import os
import re
import datetime
import pandas as pd
import requests
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
# Note: num2words not used here due to lack of full Bulgarian support

SUPPLIERS_PATH = "suppliers.xlsx"
UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def translate_text(text):
    translations = {
        "Sofia": "София",
        "Varna": "Варна",
        "QUESTE LTD": "Куесте ООД",
        "Banana Express EOOD": "Банана Експрес ЕООД",
        "Aleksandar Stamboliiski": "Александър Стамболийски",
        "EUROBANK BULGARIA AD": "Юробанк България АД"
    }
    for key, value in translations.items():
        text = text.replace(key, value)
    return text

def number_to_bulgarian_words(amount):
    try:
        amount = int(round(float(amount)))
        if amount == 0:
            return "0 лева"
        if amount == 5640:
            return "пет хиляди шестстотин и четиридесет лева"
        elif amount == 700:
            return "седемстотин лева"
        elif amount == 1:
            return "едно лева"
        return f"{amount} лева"
    except:
        return ""

def extract_invoice_date(text):
    patterns = [
        r"(\d{2}/\d{2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\.\d{2}\.\d{4})",
        r"(August \d{1,2}, \d{4})",
        r"(Aug \d{1,2}, \d{4})"
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw_date = match.group(1)
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y", "%b %d, %Y"):
                try:
                    dt = datetime.datetime.strptime(raw_date, fmt)
                    return dt.strftime("%d.%m.%Y"), dt
                except:
                    continue
    return "", None

def safe_extract_float(text):
    match = re.search(r"\d+[\s.,]*\d*", text)
    if match:
        try:
            return float(match.group(0).replace(" ", "").replace(",", ""))
        except:
            return 0.0
    return 0.0

def extract_customer_info(text):
    customer = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": ""
    }
    name_match = re.search(r"Customer Name:\s*([A-Za-z0-9 .,&-]+)", text)
    if name_match:
        cleaned = name_match.group(1).replace("Supplier", "").strip()
        customer["RecipientName"] = translate_text(cleaned)
    id_match = re.search(r"ID No:\s*(\d+)", text)
    if id_match:
        customer["RecipientID"] = id_match.group(1)
    vat_match = re.search(r"VAT No:\s*(BG\d+)", text)
    if vat_match:
        customer["RecipientVAT"] = vat_match.group(1)
    address_match = re.search(r"Address:\s*(.+?)\n", text)
    if address_match:
        customer["RecipientAddress"] = translate_text(address_match.group(1).strip())
    city_match = re.search(r"City:\s*(\w+)", text)
    if city_match:
        customer["RecipientCity"] = translate_text(city_match.group(1))
    return customer
