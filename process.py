import os
import re
import datetime
import pandas as pd
import requests
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
from num2words import num2words

SUPPLIERS_PATH = "suppliers.xlsx"
UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def translate_text(text):
    translations = {
        "Sofia": "София",
        "Varna": "Варна",
        "QUESTE LTD": "Куесте ООД",
        "Banana Express EOOD": "Банана Експрес ЕООД",
        "BGN": "лв",
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
        return num2words(amount, lang='bg') + " лева"
    except:
        return ""

def extract_invoice_date(text):
    patterns = [
        r"(\d{2}/\d{2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\.\d{2}\.\d{4})"
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw_date = match.group(1)
            try:
                dt = datetime.datetime.strptime(raw_date, "%d/%m/%Y")
            except:
                try:
                    dt = datetime.datetime.strptime(raw_date, "%Y-%m-%d")
                except:
                    dt = datetime.datetime.strptime(raw_date, "%d.%m.%Y")
            return dt.strftime("%d.%m.%Y"), dt
    return "", None

def safe_extract_float(text):
    match = re.search(r"([\d\s.,]+)", text)
    if match:
        return float(match.group(1).replace(" ", "").replace(",", ""))
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
        address = translate_text(address_match.group(1))
        customer["RecipientAddress"] = address
    city_match = re.search(r"City:\s*(\w+)", text)
    if city_match:
        customer["RecipientCity"] = translate_text(city_match.group(1))
    return customer
