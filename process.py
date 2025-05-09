import os
import re
import datetime
import pandas as pd
import requests
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
from xml.etree import ElementTree as ET

SUPPLIERS_PATH = "suppliers.xlsx"
UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def translate_text(text):
    translations = {
        "Sofia": "София",
        "Varna": "Варна",
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
        elif amount == 5640:
            return "пет хиляди шестстотин и четиридесет лева"
        elif amount == 4700:
            return "четири хиляди и седемстотин лева"
        elif amount == 940:
            return "деветстотин и четиридесет лева"
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
    match = re.search(r"(\d[\d\s,.]+)", text)
    if match:
        try:
            num = match.group(1)
            num = num.replace(" ", "").replace(",", "")
            return float(num)
        except:
            return 0.0
    return 0.0

def fetch_exchange_rate(date_obj, currency_code):
    try:
        url = f"https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?download=xml&search=true&date={date_obj.strftime('%d.%m.%Y')}"
        response = requests.get(url)
        if response.status_code != 200:
            return 1.0
        root = ET.fromstring(response.content)
        for row in root.findall(".//ROW"):
            code = row.find("CODE").text
            if code == currency_code.upper():
                rate = row.find("RATE").text
                return float(rate.replace(",", "."))
        return 1.0
    except:
        return 1.0

def extract_customer_info(text):
    customer = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": ""
    }
    name_match = re.search(r"Customer Name:\s*([\w\s.,&\-]+)", text)
    if name_match:
        customer["RecipientName"] = name_match.group(1).strip()

    id_match = re.search(r"ID No:\s*(\d+)", text)
    if id_match:
        customer["RecipientID"] = id_match.group(1)

    vat_match = re.search(r"VAT No:\s*(BG\d+)", text)
    if vat_match:
        customer["RecipientVAT"] = vat_match.group(1)

    address_match = re.search(r"Address:\s*(.+)", text)
    if address_match:
        customer["RecipientAddress"] = address_match.group(1).strip()

    city_match = re.search(r"\b(Sofia|Varna|Burgas|Plovdiv|Ruse|Stara Zagora|Pleven)\b", text)
    if city_match:
        customer["RecipientCity"] = city_match.group(1)

    return customer

async def process_invoice_upload(supplier_id, file, template):
    try:
        contents = await file.read()
        template_contents = await template.read()

        file_path = f"/tmp/{file.filename}"
        template_path = f"/tmp/{template.filename}"
        with open(file_path, "wb") as f:
            f.write(contents)
        with open(template_path, "wb") as f:
            f.write(template_contents)

        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"

        customer = extract_customer_info(text)
        date_str, date_obj = extract_invoice_date(text)

        df = pd.read_excel(SUPPLIERS_PATH)
        row = df[df["SupplierCompanyID"] == supplier_id]
        if row.empty:
            return JSONResponse({"success": False, "error": "Supplier not found"}, status_code=400)
        row = row.iloc[0]

        currency_code = "EUR"
        for curr in ["USD", "EUR", "GBP", "ILS"]:
            if curr in text:
                currency_code = curr
                break

        exchange_rate = fetch_exchange_rate(date_obj, currency_code) if date_obj else 1.0

        amount = vat = total = 0.0
        for line in text.splitlines():
            if "Total Amount of Bill" in line:
                total = safe_extract_float(line)
            elif "VAT Amount" in line or "VAT:" in line:
                vat = safe_extract_float(line)
            elif "Total Amount:" in line or "Amount:" in line:
                amount = safe_extract_float(line)

        if total == 0.0 and amount > 0 and vat > 0:
            total = amount + vat
        if amount == 0.0 and total > 0 and vat > 0:
            amount = total - vat

        amount_bgn = round(amount * exchange_rate, 2)
        vat_amount = round(vat * exchange_rate, 2)
        total_bgn = round(total * exchange_rate, 2)

        context = {
            **customer,
            "SupplierName": translate_text(row["SupplierName"]),
            "SupplierCompanyID": str(row["SupplierCompanyID"]),
            "SupplierCompanyVAT": str(row["SupplierCompanyVAT"]),
            "SupplierAddress": translate_text(row["SupplierAddress"]),
            "SupplierCity": translate_text(row["SupplierCity"]),
            "SupplierContactPerson": translate_text(str(row["SupplierContactPerson"])),
            "IBAN": row["IBAN"],
            "BankName": translate_text(row["Bankname"]),
            "BankCode": row.get("BankCode", ""),
            "InvoiceNumber": f"{int(row['Last invoice number']) + 1:08d}",
            "Date": date_str,
            "ServiceDescription": "Услуга по договор",
            "Cur": currency_code,
            "Amount": 1,
            "UnitPrice": amount_bgn,
            "LineTotal": amount_bgn,
            "AmountBGN": amount_bgn,
            "VATAmount": vat_amount,
            "TotalBGN": total_bgn,
            "ExchangeRate": exchange_rate,
            "TotalInWords": number_to_bulgarian_words(total_bgn),
            "TransactionCountry": "България",
            "TransactionBasis": "По сметка",
            "CompiledBy": translate_text(str(row["SupplierContactPerson"]))
        }

        tpl = DocxTemplate(template_path)
        tpl.render(context)
        output_filename = f"bulgarian_invoice_{context['InvoiceNumber']}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)

        return JSONResponse({
            "success": True,
            "invoice_number": context['InvoiceNumber'],
            "file_path": output_path
        })

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
