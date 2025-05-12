import os
import re
import datetime
import pandas as pd
import requests
import pytesseract
from pdf2image import convert_from_path
from fastapi import UploadFile
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
from xml.etree import ElementTree as ET
from docx import Document
import traceback
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from tempfile import NamedTemporaryFile

SUPPLIERS_PATH = "suppliers.xlsx"
TEMPLATE_PATH = "BulTrans_Template_FinalFInal.docx"
UPLOAD_DIR = "/tmp/uploads"
DRIVE_FOLDER_ID = "1JUTWRpBGKemiH6x89lHbV7b5J53fud3V"

os.makedirs(UPLOAD_DIR, exist_ok=True)

def log(msg):
    print(f"[BulTrans LOG] {msg}", flush=True)

def auto_translate(text, target_lang="bg"):
    if not text.strip():
        return text
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload = {"q": text, "target": target_lang}
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json()["data"]["translations"][0]["translatedText"]
    except Exception as e:
        log(f"Translation failed: {e}")
    return text

def number_to_bulgarian_words(amount):
    try:
        amount = int(round(float(amount)))
        if amount == 0:
            return "0 лева"
        return f"{amount} лева"
    except:
        return ""

def extract_invoice_date(text):
    patterns = [
        r"(\d{2}/\d{2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\.\d{2}\.\d{4})",
        r"(\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4})",
        r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4})"
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
            num = match.group(1).replace(" ", "").replace(",", "")
            return float(num)
        except:
            return 0.0
    return 0.0

def fetch_exchange_rate(date_obj, currency_code):
    try:
        url = f"https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?download=xml&search=true&date={date_obj.strftime('%d.%m.%Y')}"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return 1.0
        root = ET.fromstring(response.content)
        for row in root.findall(".//ROW"):
            code = row.find("CODE").text
            if code == currency_code.upper():
                rate = row.find("RATE").text
                return float(rate.replace(",", "."))
    except Exception as e:
        log(f"Exchange rate fetch failed: {e}")
    return 1.0

def extract_text_from_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip():
            return text
        images = convert_from_path(file_path)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    except Exception as e:
        log(f"PDF text extraction failed: {e}")
        return ""

def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        log(f"DOCX text extraction failed: {e}")
        return ""

def clean_recipient_name(line):
    return re.sub(r"(?i)(Supplier|Доставчик)", "", line).strip()

def extract_service_description(lines):
    for line in reversed(lines):
        if len(line) > 20 and not re.search(r"(?i)(Quantity|Total|Amount|VAT|Net|Общо|Bank|IBAN|Account|Invoice|номер)", line):
            return line.strip()
    return ""

def extract_customer_info(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    customer = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": "",
        "ServiceDescription": extract_service_description(lines)
    }

    for line in lines:
        if re.search(r"(?i)(Customer Name|Bill To|Invoice To)", line):
            if ':' in line:
                value = line.split(':', 1)[1].strip()
                if 'Supplier' not in value and 'Доставчик' not in value:
                    customer["RecipientName"] = clean_recipient_name(value)
        elif re.search(r"(?i)(ID No|Tax ID|Identification Number)", line):
            match = re.search(r"\d+", line)
            if match:
                customer["RecipientID"] = match.group(0)
        elif re.search(r"(?i)(VAT No|VAT|VAT ID|Tax Number)", line):
            match = re.search(r"BG\d+", line)
            if match:
                customer["RecipientVAT"] = match.group(0)
        elif re.search(r"(?i)(Address|Billing Address)", line):
            customer["RecipientAddress"] = line.split(":")[-1].strip()
        elif re.search(r"(?i)(City|Sofia|Varna|Burgas|Plovdiv|Ruse|Stara Zagora|Pleven)", line):
            if ':' in line:
                customer["RecipientCity"] = line.split(':', 1)[1].strip()
            else:
                customer["RecipientCity"] = line.strip()

    return customer

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json:
        raise ValueError("Missing GOOGLE_CREDS_JSON")
    with NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp_file:
        temp_file.write(creds_json)
        temp_file.flush()
        credentials = service_account.Credentials.from_service_account_file(temp_file.name, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=credentials)

def upload_to_drive(local_path, filename):
    log("🔼 Uploading file to Google Drive...")
    service = get_drive_service()
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaFileUpload(local_path, resumable=True)
    uploaded_file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    service.permissions().create(fileId=uploaded_file["id"], body={"type": "anyone", "role": "reader"}).execute()
    return f"https://drive.google.com/file/d/{uploaded_file['id']}/view?usp=sharing"

async def process_invoice_upload(supplier_id: str, file: UploadFile):
    try:
        log("🚀 Starting invoice processing...")
        contents = await file.read()
        file_path = f"/tmp/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(contents)

        text = extract_text_from_pdf(file_path) if file.filename.endswith(".pdf") else extract_text_from_docx(file_path)
        lines = text.splitlines()
        customer = extract_customer_info(text)

        required_fields = ["RecipientName", "RecipientID", "RecipientVAT", "RecipientAddress", "RecipientCity"]
        missing_fields = [f for f in required_fields if not customer.get(f)]
        if missing_fields:
            return JSONResponse({"success": False, "error": f"Missing required fields in invoice: {', '.join(missing_fields)}"}, status_code=400)

        date_str, date_obj = extract_invoice_date(text)
        if not date_obj:
            return JSONResponse({"success": False, "error": "Invoice date not found or unrecognized format"}, status_code=400)

        df = pd.read_excel(SUPPLIERS_PATH)
        row = df[df["SupplierCompanyID"] == int(supplier_id)]
        if row.empty:
            return JSONResponse({"success": False, "error": "Supplier not found"}, status_code=400)
        row = row.iloc[0]

        currency_code = next((curr for curr in ["USD", "EUR", "GBP", "ILS", "BGN"] if curr in text), "EUR")
        exchange_rate = fetch_exchange_rate(date_obj, currency_code) if currency_code != "BGN" else 1.0

        amount = vat = total = 0.0
        previous_line = ""
        for line in lines:
            if re.search(r"(?i)Total Amount of Bill", line):
                previous_line = "total"
            elif re.search(r"(?i)VAT Amount", line):
                previous_line = "vat"
            elif re.search(r"(?i)Subtotal|Amount", line):
                previous_line = "amount"
            elif re.search(r"(?i)\d+[\d\s,.]*", line):
                value = safe_extract_float(line)
                if previous_line == "total" and value > 0:
                    total = value
                elif previous_line == "vat" and value > 0:
                    vat = value
                elif previous_line == "amount" and value > 0:
                    amount = value
                previous_line = ""

        if total == 0.0 and amount > 0 and vat > 0:
            total = amount + vat
        if amount == 0.0 and total > 0 and vat > 0:
            amount = total - vat

        amount_bgn = round(amount * exchange_rate, 2)
        vat_amount = round(vat * exchange_rate, 2)
        total_bgn = round(total * exchange_rate, 2)

        invoice_number = f"{int(row['Last invoice number']) + 1:08d}"
        df.at[row.name, "Last invoice number"] += 1
        df.to_excel(SUPPLIERS_PATH, index=False)

        context = {
            "RecipientName": auto_translate(customer["RecipientName"]),
            "RecipientID": customer["RecipientID"],
            "RecipientVAT": customer["RecipientVAT"],
            "RecipientAddress": auto_translate(customer["RecipientAddress"]),
            "RecipientCity": auto_translate(customer["RecipientCity"]),
            "SupplierName": auto_translate(str(row["SupplierName"])),
            "SupplierCompanyID": str(row["SupplierCompanyID"]),
            "SupplierCompanyVAT": str(row["SupplierCompanyVAT"]),
            "SupplierAddress": auto_translate(str(row["SupplierAddress"])),
            "SupplierCity": auto_translate(str(row["SupplierCity"])),
            "SupplierContactPerson": auto_translate(str(row["SupplierContactPerson"])),
            "IBAN": row["IBAN"],
            "BankName": auto_translate(str(row["Bankname"])),
            "BankCode": row.get("BankCode", ""),
            "InvoiceNumber": invoice_number,
            "Date": date_str,
            "ServiceDescription": auto_translate(customer["ServiceDescription"] or "Услуга по договор"),
            "Cur": "BGN",
            "Amount": 1,
            "UnitPrice": amount_bgn,
            "LineTotal": amount_bgn,
            "AmountBGN": amount_bgn,
            "VATAmount": vat_amount,
            "TotalBGN": total_bgn,
            "ExchangeRate": exchange_rate,
            "TotalInWords": number_to_bulgarian_words(total_bgn),
            "TransactionCountry": "България",
            "TransactionBasis": "По сметка"
        }

        tpl = DocxTemplate(TEMPLATE_PATH)
        tpl.render(context)
        output_filename = f"bulgarian_invoice_{context['InvoiceNumber']}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)

        drive_link = upload_to_drive(output_path, output_filename)

        return JSONResponse({"success": True, "data": {"invoice_number": context['InvoiceNumber'], "drive_link": drive_link}})

    except Exception as e:
        log("❌ EXCEPTION OCCURRED:")
        log(traceback.format_exc())
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
