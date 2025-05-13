
import os
import re
import datetime
import pandas as pd
import requests
import pytesseract
from pdf2image import convert_from_path
from fastapi import UploadFile, APIRouter
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

router = APIRouter()

def log(msg):
    print(f"[BulTrans LOG] {msg}", flush=True)

def auto_translate(text, target_lang="bg"):
    print("[DEBUG] GOOGLE_API_KEY:", os.getenv("GOOGLE_API_KEY"))
    if not text.strip():
        return text
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            log("⚠️ Missing GOOGLE_API_KEY in environment variables")
            return text
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload = {"q": text, "target": target_lang}
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json()["data"]["translations"][0]["translatedText"]
        else:
            log(f"⚠️ Translation API error: {response.status_code} - {response.text}")
    except Exception as e:
        log(f"❌ Translation failed: {e}")
    return text

def transliterate_to_bulgarian(text):
    table = {
        "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф",
        "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л",
        "m": "м", "n": "н", "o": "о", "p": "п", "q": "кю", "r": "р",
        "s": "с", "t": "т", "u": "у", "v": "в", "w": "у", "x": "кс",
        "y": "й", "z": "з",
        "A": "А", "B": "Б", "C": "Ц", "D": "Д", "E": "Е", "F": "Ф",
        "G": "Г", "H": "Х", "I": "И", "J": "Дж", "K": "К", "L": "Л",
        "M": "М", "N": "Н", "O": "О", "P": "П", "Q": "Кю", "R": "Р",
        "S": "С", "T": "Т", "U": "У", "V": "В", "W": "У", "X": "Кс",
        "Y": "Й", "Z": "З",
        ".": ".", " ": " ", ",": ",", "-": "-", "&": "и"
    }
    return "".join(table.get(char, char) for char in text)

def number_to_bulgarian_words(amount, as_words=False):
    try:
        leva = int(amount)
        stotinki = int(round((amount - leva) * 100))
        if as_words:
            word_map = {
                0: "нула", 1: "един", 2: "два", 3: "три", 4: "четири", 5: "пет",
                6: "шест", 7: "седем", 8: "осем", 9: "девет"
            }
            leva_words = f"{word_map.get(leva, leva)} лева"
        else:
            leva_words = f"{leva} лв."
        if stotinki > 0:
            return f"{leva_words} и {stotinki:02d} ст."
        return leva_words
    except:
        return ""

def extract_invoice_date(text):
    patterns = [
        r"(\d{2}/\d{2}/\d{4})", r"(\d{4}-\d{2}-\d{2})",
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

def extract_text_from_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip(): return text
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
    line = line.replace("Supplier", "").replace("Customer", "").replace("Client", "")
    return ' '.join(line.strip().split())

def extract_service_line(lines):
    for line in lines:
        if re.search(r"(?i)(Service|услуга|agreement|based)", line):
            return line.strip()
    return ""

def extract_date_from_service(service_line):
    match = re.search(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", service_line)
    if match:
        try:
            dt = datetime.datetime.strptime(match.group(1).replace('/', '.').replace('-', '.'), "%d.%m.%Y")
            return dt.strftime("%B %Y")
        except:
            return None
    return None

def safe_extract_float(text):
    match = re.search(r"(\d[\d\s,.]+)", text)
    if match:
        try:
            num = match.group(1).replace(" ", "").replace(",", "")
            return float(num)
        except:
            return 0.0
    return 0.0

def extract_amount(text):
    for line in text.splitlines()[::-1]:  # עובר מהסוף להתחלה
        if re.search(r"(?i)(total|subtotal|amount due|grand total)", line):
            val = safe_extract_float(line)
            if val > 0:
                return val
    return 0.0


    match = re.search(r"(\d[\d\s,.]+)", text)
    if match:
        try:
            num = match.group(1).replace(" ", "").replace(",", "")
            return float(num)
        except:
            return 0.0
    return 0.0

def extract_currency_code(text):
    # מנסה לזהות את המטבע רק מהשורות שמכילות סכומים
    lines = text.splitlines()
    for line in lines:
        if re.search(r"\b\d+[.,]?\d*\s*(BGN|EUR|USD|ILS|GBP)\b", line):
            match = re.search(r"(BGN|EUR|USD|ILS|GBP)", line)
            if match:
                return match.group(1)
    return "EUR"  # ברירת מחדל אם לא נמצא שום מטבע ברור

def extract_quantity(text):
    match = re.search(r"(\d+(?:\.\d+)?)(?=\s*(EUR|USD|ILS|BGN|GBP))", text)
    if match:
        return float(match.group(1))
    return 1.0

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

def extract_unit_price(currency_code, date_obj):
    if currency_code == "EUR":
        return 1.95583
    elif currency_code == "BGN":
        return 1.0
    return fetch_exchange_rate(date_obj, currency_code)

def extract_customer_info(text, supplier_name=""):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    service_line = extract_service_line(lines)
    service_date = extract_date_from_service(service_line)
if  service_date:
    service_translated = f"{auto_translate(service_line)} от {auto_translate(service_date)}"
else:
    service_translated = auto_translate(service_line)

    customer = {
        "RecipientName": "",
        "RecipientID": "",
        "RecipientVAT": "",
        "RecipientAddress": "",
        "RecipientCity": "",
        "RecipientCountry": "",
        "ServiceDescription": service_translated
    }

    for line in lines:
        if re.search(r"(?i)(Customer Name|Bill To|Invoice To|Client)", line):
            parts = line.split(":", 2)
            if len(parts) >= 2:
                raw_name = parts[1].split(":")[0].strip()
                pattern = re.compile(re.escape(supplier_name), re.IGNORECASE)
                raw_name = pattern.sub("", raw_name).strip()
                raw_name = re.sub(r"(?i)supplier|vendor|company|firm", "", raw_name)
                raw_name = clean_recipient_name(raw_name)
                if raw_name:
                    customer["RecipientName"] = transliterate_to_bulgarian(raw_name)

        elif re.search(r"(?i)(ID No|Tax ID)", line):
            m = re.search(r"\d+", line)
            if m:
                customer["RecipientID"] = m.group(0)

        elif re.search(r"(?i)(VAT|VAT No)", line):
            m = re.search(r"BG\d+", line)
            if m:
                customer["RecipientVAT"] = m.group(0)

        elif re.search(r"(?i)(Address|Billing Address)", line):
            raw_address = line.split(":", 1)[-1].strip()
            customer["RecipientAddress"] = transliterate_to_bulgarian(raw_address)

        elif re.search(r"(?i)(City|Sofia|Plovdiv|Varna|Burgas)", line):
            val = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
            customer["RecipientCity"] = auto_translate(val)

        elif re.search(r"(?i)(Country|Location)", line):
            raw_country = line.split(":", 1)[-1].strip()
            if raw_country:
                customer["RecipientCountry"] = auto_translate(raw_country)

    # אם לא זוהתה מדינה בכלל, הגדר ברירת מחדל
    if not customer["RecipientCountry"]:
        customer["RecipientCountry"] = "България"

    return customer

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json:
        raise ValueError("Missing GOOGLE_CREDS_JSON")
    with NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp_file:
        temp_file.write(creds_json)
        temp_file.flush()
        credentials = service_account.Credentials.from_service_account_file(
            temp_file.name, scopes=["https://www.googleapis.com/auth/drive"]
        )
    return build("drive", "v3", credentials=credentials)

def upload_to_drive(local_path, filename):
    log("Uploading to Drive...")
    service = get_drive_service()
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaFileUpload(local_path, resumable=True)
    uploaded_file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    service.permissions().create(fileId=uploaded_file["id"], body={"type": "anyone", "role": "reader"}).execute()
    return f"https://drive.google.com/file/d/{uploaded_file['id']}/view"

@router.post("/process-invoice/")
async def process_invoice_upload(supplier_id: str, file: UploadFile):
    try:
        contents = await file.read()
        file_path = f"/tmp/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(contents)
        text = extract_text_from_pdf(file_path) if file.filename.endswith(".pdf") else extract_text_from_docx(file_path)
        lines = text.splitlines()
        df = pd.read_excel(SUPPLIERS_PATH)
        row = df[df["SupplierCompanyID"] == int(supplier_id)]
        if row.empty:
            return JSONResponse({"success": False, "error": "Supplier not found"}, status_code=400)
        row = row.iloc[0]
        customer = extract_customer_info(text, row["SupplierName"])
        date_str, date_obj = extract_invoice_date(text)
        if not date_obj:
            date_obj = datetime.datetime.today()
            date_str = date_obj.strftime("%d.%m.%Y")
        currency_code = extract_currency_code(text)
        log(f"🔎 Detected currency: {currency_code}")
        amount = extract_amount(text)  # זה הסכום המקורי מהחשבונית
        unit_price = extract_unit_price(currency_code, date_obj)
        line_total = round(amount * unit_price, 2)
        vat_amount = round(line_total * 0.2, 2)
        total_bgn = round(line_total + vat_amount, 2)
        invoice_number = f"{int(row['Last invoice number']) + 1:08d}"
        df.at[row.name, "Last invoice number"] += 1
        df.to_excel(SUPPLIERS_PATH, index=False)
        context = {
            "RecipientName": customer["RecipientName"],
            "RecipientID": customer["RecipientID"],
            "RecipientVAT": customer["RecipientVAT"],
            "RecipientAddress": f"{customer['RecipientAddress']}, {customer['RecipientCountry']}",
            "RecipientCity": customer["RecipientCity"],
            "RecipientCountry": customer["RecipientCountry"],
            "SupplierName": auto_translate(str(row["SupplierName"])),
            "SupplierCompanyID": str(row["SupplierCompanyID"]),
            "SupplierCompanyVAT": str(row["SupplierCompanyVAT"]),
            "SupplierAddress": auto_translate(str(row["SupplierAddress"]) + (", " + str(row["SupplierCountry"]) if pd.notna(row.get("SupplierCountry")) else "")),
            "SupplierCity": auto_translate(str(row["SupplierCity"])),
            "SupplierCountry": auto_translate(str(row.get("SupplierCountry", "България"))),
            "SupplierContactPerson": auto_translate(str(row["SupplierContactPerson"])),
            "IBAN": row["IBAN"],
            "BankName": auto_translate(str(row["Bankname"])),
            "BankCode": row.get("BankCode", ""),
            "InvoiceNumber": invoice_number,
            "Date": date_str,
            "ServiceDescription": customer["ServiceDescription"],
            "Cur": currency_code,
            "Amount": amount,
            "UnitPrice": unit_price,
            "LineTotal": line_total,
            "AmountBGN": line_total,
            "VATAmount": vat_amount,
            "TotalBGN": total_bgn,
            "ExchangeRate": unit_price,
            "TotalInWords": number_to_bulgarian_words(total_bgn, as_words=True),
            "TransactionCountry": "България",
            "TransactionBasis": "По сметка"
        }
        tpl = DocxTemplate(TEMPLATE_PATH)
        tpl.render(context)
        output_filename = f"bulgarian_invoice_{invoice_number}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)
        drive_link = upload_to_drive(output_path, output_filename)
        return JSONResponse({"success": True, "data": {"invoice_number": invoice_number, "drive_link": drive_link}})
    except Exception as e:
        log("❌ EXCEPTION OCCURRED:")
        log(traceback.format_exc())
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
