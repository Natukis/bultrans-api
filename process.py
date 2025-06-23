
import os
import re
import datetime
import pandas as pd
import requests
import pytesseract
import traceback
import time
from pdf2image import convert_from_path
from fastapi import UploadFile, APIRouter, HTTPException
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
from xml.etree import ElementTree as ET
from docx import Document
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, HttpRequest
from tempfile import NamedTemporaryFile

# --- Configuration from Environment Variables ---
SUPPLIERS_PATH = os.getenv("SUPPLIERS_PATH", "suppliers.xlsx")
TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "EUR")
DEFAULT_VAT_PERCENT = float(os.getenv("DEFAULT_VAT_PERCENT", "20.0"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
UPLOAD_DIR = "/tmp/uploads"
GOOGLE_API_TIMEOUT = int(os.getenv("GOOGLE_API_TIMEOUT", "20"))

os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)

router = APIRouter()

# --- Core Helper Functions ---

def log(msg):
    print(f"[{datetime.datetime.now()}] {msg}", flush=True)

def is_cyrillic(text):
    return bool(re.search('[\u0400-\u04FF]', text))

def auto_translate(text, target_lang="bg"):
    if not text or not isinstance(text, str) or not text.strip(): return ""
    try:
        if is_cyrillic(text): return text
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: 
            log("ERROR: Missing GOOGLE_API_KEY. Cannot translate.")
            return None
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload = {"q": text, "target": target_lang}
        response = requests.post(url, json=payload, timeout=GOOGLE_API_TIMEOUT)
        if response.status_code == 200:
            return response.json()["data"]["translations"][0]["translatedText"]
        log(f"Translation API error: {response.status_code} - {response.text}")
        return None # Return None on API error
    except Exception as e:
        log(f"❌ Translation failed: {e}")
        return None

def transliterate_to_bulgarian(text):
    if not text: return ""
    table = { "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "кю", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "у", "x": "кс", "y": "й", "z": "з", "A": "А", "B": "Б", "C": "Ц", "D": "Д", "E": "Е", "F": "Ф", "G": "Г", "H": "Х", "I": "И", "J": "Дж", "K": "К", "L": "Л", "M": "М", "N": "Н", "O": "О", "P": "П", "Q": "Кю", "R": "Р", "S": "С", "T": "Т", "U": "У", "V": "В", "W": "У", "X": "Кс", "Y": "Й", "Z": "З", ".": ".", " ": " ", ",": ",", "-": "-", "&": "и"}
    return "".join(table.get(char, char) for char in text)

def number_to_bulgarian_words(amount, as_words=True):
    # ⭐️ Full implementation restored.
    try:
        leva = int(amount)
        stotinki = int(round((amount - leva) * 100))
        if as_words:
            word_map = {0: "нула", 1: "един", 2: "два", 3: "три", 4: "четири", 5: "пет", 6: "шест", 7: "седем", 8: "осем", 9: "девет", 10: "десет", 11: "единадесет", 12: "дванадесет", 13: "тринадесет", 14: "четиринадесет", 15: "петнадесет", 16: "шестнадесет", 17: "седемнадесет", 18: "осемнадесет", 19: "деветнадесет", 20: "двадесет", 30: "тридесет", 40: "четиридесет", 50: "петдесет", 60: "шестдесет", 70: "седемдесет", 80: "осемдесет", 90: "деветдесет"}
            def convert_to_words(n):
                if n in word_map: return word_map[n]
                parts = []
                if n >= 1000:
                    thousands = n // 1000
                    if thousands == 1: parts.append("хиляда")
                    elif thousands == 2: parts.append("две хиляди")
                    else: parts.append(f"{convert_to_words(thousands)} хиляди")
                    n %= 1000
                if n >= 100:
                    hundreds_map = {1: "сто", 2: "двеста", 3: "триста", 4: "четиристотин", 5: "петстотин", 6: "шестстотин", 7: "седемстотин", 8: "осемстотин", 9: "деветстотин"}
                    hundreds = n // 100
                    parts.append(hundreds_map.get(hundreds))
                    n %= 100
                if n > 0:
                    if n <= 20:
                        parts.append(word_map[n])
                    else:
                        tens = n // 10 * 10
                        ones = n % 10
                        tens_word = word_map[tens]
                        if ones > 0: parts.append(f"{tens_word} и {word_map[ones]}")
                        else: parts.append(tens_word)
                return " ".join(parts)
            leva_words = convert_to_words(leva).capitalize()
            return f"{leva_words} лева и {stotinki:02d} стотинки"
        else:
            leva_words = f"{leva} лв."
            return f"{leva_words} и {stotinki:02d} ст." if stotinki > 0 else leva_words
    except Exception as e:
        log(f"Error in number_to_bulgarian_words: {e}")
        return ""

def fetch_exchange_rate(date_obj, currency_code):
    if currency_code.upper() == "EUR": return 1.95583
    if currency_code.upper() == "BGN": return 1.0
    try:
        url = f"https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?download=xml&search=true&date={date_obj.strftime('%d.%m.%Y')}"
        response = requests.get(url, timeout=10)
        if response.status_code != 200: return None
        root = ET.fromstring(response.content)
        for row in root.findall(".//ROW"):
            if row.find("CODE").text == currency_code.upper():
                rate = float(row.find("RATE").text.replace(",", "."))
                ratio = float(row.find("RATIO").text.replace(",", "."))
                return rate / ratio
        return None
    except Exception as e:
        log(f"Exchange rate fetch failed: {e}")
        return None

class TimeoutHttpRequest(HttpRequest):
    def __init__(self, *args, **kwargs):
        if 'timeout' not in kwargs:
            kwargs['timeout'] = GOOGLE_API_TIMEOUT
        super().__init__(*args, **kwargs)

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json: raise ValueError("Missing GOOGLE_CREDS_JSON")
    if not DRIVE_FOLDER_ID: raise ValueError("Missing DRIVE_FOLDER_ID")
    with NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as tf:
        tf.write(creds_json)
        path = tf.name
    try:
        creds = service_account.Credentials.from_service_account_file(path, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds, cache_discovery=False, requestBuilder=TimeoutHttpRequest)
    finally:
        os.remove(path)

def upload_to_drive(local_path, filename):
    # ⭐️ IMPROVEMENT: Added retry mechanism
    log(f"Uploading '{filename}' to Google Drive...")
    retries = 3
    delay = 5
    for i in range(retries):
        try:
            service = get_drive_service()
            file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
            media = MediaFileUpload(local_path, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
            service.permissions().create(fileId=file["id"], body={"type": "anyone", "role": "reader"}).execute()
            link = file.get("webViewLink")
            log(f"Successfully uploaded. Link: {link}")
            return link
        except Exception as e:
            log(f"❌ Google Drive upload attempt {i+1}/{retries} failed: {e}")
            if i < retries - 1:
                log(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                log("All upload retries failed.")
                return None
    return None

# --- New, Improved & Refactored Functions ---

def extract_text_from_file(file_path, filename):
    log(f"Extracting text from '{filename}'")
    if filename.lower().endswith(".pdf"):
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(file_path).pages)
            if len(text.strip()) > 50: return text
            log("Fallback to OCR.")
            return "\n".join(pytesseract.image_to_string(img, config='--psm 6') for img in convert_from_path(file_path, dpi=300))
        except Exception as e:
            log(f"PDF extraction failed: {e}"); return ""
    return ""

def clean_number(num_str):
    if not isinstance(num_str, str): return 0.0
    num_str = re.sub(r'[^\d\.,-]', '', num_str)
    if ',' in num_str and '.' in num_str:
        if num_str.rfind(',') > num_str.rfind('.'): num_str = num_str.replace('.', '').replace(',', '.')
        else: num_str = num_str.replace(',', '')
    elif ',' in num_str: num_str = num_str.replace(',', '.')
    try: return float(num_str)
    except: return 0.0

def extract_invoice_date(text):
    patterns = [r"(\d{2}/\d{2}/\d{4})", r"(\d{4}-\d{2}-\d{2})", r"(\d{2}\.\d{2}\.\d{4})", r"(\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s\d{1,2},\s\d{4})", r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s\d{1,2},\s\d{4})"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw_date = match.group(1)
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y", "%b %d, %Y"):
                try:
                    dt = datetime.datetime.strptime(raw_date, fmt)
                    return dt.strftime("%d.%m.%Y"), dt
                except ValueError: continue
    return None, None

def extract_customer_details(text, supplier_name=""):
    details = {'name': '', 'vat': '', 'id': '', 'address': '', 'city': '', 'country': 'България'}
    lines = text.splitlines()
    customer_keywords = ['customer name:', 'bill to:', 'invoice to:', 'spett.le', 'client:']
    for line in lines:
        line_lower = line.lower()
        if not details['name'] and any(keyword in line_lower for keyword in customer_keywords):
            raw_name = line.split(':', 1)[-1].strip()
            if supplier_name:
                raw_name = re.sub(re.escape(supplier_name), '', raw_name, flags=re.IGNORECASE)
            details['name'] = re.sub(r'(?i)\bsupplier\b', '', raw_name).strip()
        elif not details['vat'] and "vat no:" in line_lower:
            vat_match = re.search(r'(BG\d+)', line, re.IGNORECASE)
            if vat_match: details['vat'] = vat_match.group(1)
        elif not details['id'] and "id no:" in line_lower:
             id_match = re.search(r'\b(\d{9,})\b', line)
             if id_match: details['id'] = id_match.group(0)
        elif not details['address'] and "address:" in line_lower:
            details['address'] = line.split(':', 1)[-1].strip()
        elif not details['city'] and "city:" in line_lower:
            city_name = line.split(':', 1)[-1].strip()
            details['city'] = auto_translate(city_name)
    log(f"Extracted Customer Details: {details}")
    return details

def extract_service_date(description):
    bg_months = {1: "Януари", 2: "Февруари", 3: "Март", 4: "Април", 5: "Май", 6: "Юни", 7: "Юли", 8: "Август", 9: "Септември", 10: "Октомври", 11: "Ноември", 12: "Декември"}
    match1 = re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b', description, re.IGNORECASE)
    if match1:
        month_name_en, year = match1.group(1), match1.group(2)
        try:
            month_dt = datetime.datetime.strptime(month_name_en, "%B")
            return f"м.{bg_months[month_dt.month]} {year}"
        except ValueError: pass
    match2 = re.search(r'\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b', description)
    if match2:
        try:
            parts = re.split(r'[./-]', match2.group(1))
            if len(parts) == 3:
                month, year = int(parts[1]), int(parts[2])
                if year < 100: year += 2000
                return f"м.{bg_months[month]} {year}"
        except: pass
    return ""

def extract_service_lines(text):
    service_items = []
    lines = text.splitlines()
    item_regex = re.compile(r"^(?P<desc>.+?)\s{2,}.*?(?P<total>[\d,]+\.\d{2})$")
    start_kw = ['description', 'descrizione', 'item', 'activity', 'amount']
    end_kw = ['subtotal', 'imponibile', 'total', 'thank you', 'tax']
    in_table = False
    for line in lines:
        line_lower = line.lower().strip()
        if any(k in line_lower for k in end_kw):
            in_table = False
            continue
        if any(k in line_lower for k in start_kw) and len(line_lower) < 50:
            in_table = True
            continue
        if in_table:
            match = item_regex.match(line.strip())
            if match:
                desc = match.group('desc').strip()
                if desc.lower() not in start_kw and len(desc) > 3:
                    service_items.append({'description': desc, 'line_total': clean_number(match.group('total')), 'ServiceDate': extract_service_date(desc)})
    if not service_items:
        log("⚠️ No structured lines found. Activating fallback.")
        total = 0
        for line in reversed(text.splitlines()):
            if 'total' in line.lower() or 'amount due' in line.lower():
                numbers = re.findall(r'[\d,]+\.\d{2}', line)
                if numbers:
                    total = clean_number(numbers[-1])
                    if total > 0: break
        if total > 0:
            service_items.append({'description': "Consulting services per invoice", 'line_total': total, 'ServiceDate': ''})
            log(f"✅ Created generic service line from total: {total}")
    return service_items

def get_template_path_by_rows(num_rows: int) -> str:
    max_supported = 5
    effective_rows = min(num_rows, max_supported) if num_rows > 0 else 1
    path = os.path.join(TEMPLATES_DIR, f"BulTrans_Template_{effective_rows}row.docx")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Template file not found: {path}")
    return path

# --- Main Endpoint ---
@router.post("/process-invoice/")
async def process_invoice_upload(supplier_id: str, file: UploadFile):
    file_path = f"/tmp/{file.filename}"
    output_path = ""
    try:
        log(f"--- Starting invoice processing for supplier: {supplier_id}, file: {file.filename} ---")
        with open(file_path, "wb") as f: f.write(await file.read())
        text = extract_text_from_file(file_path, file.filename)
        if not text: raise HTTPException(status_code=400, detail="Could not extract text from file.")

        df = pd.read_excel(SUPPLIERS_PATH)
        supplier_row = df[df["SupplierCompanyID"] == int(supplier_id)]
        if supplier_row.empty: raise HTTPException(status_code=404, detail="Supplier not found")
        supplier_data = supplier_row.iloc[0]

        customer_details = extract_customer_details(text, supplier_data["SupplierName"])
        log(f"Extracted Customer Details: {customer_details}")
        
        main_date_str, main_date_obj = extract_invoice_date(text)
        if not main_date_obj:
            raise HTTPException(status_code=400, detail="לא נמצא תאריך הנפקה בחשבונית.")
        log(f"Extracted Invoice Date: {main_date_str}")
        
        service_items = [item for item in extract_service_lines(text) if item.get('line_total', 0) > 0]
        if not service_items:
            raise HTTPException(status_code=400, detail="לא נמצאו שורות שירות חוקיות בחשבונית.")
        log(f"Extracted and validated {len(service_items)} service lines.")
        
        currency = DEFAULT_CURRENCY
        if '€' in text or 'EUR' in text.upper(): currency = 'EUR'
        elif '$' in text or 'USD' in text.upper(): currency = 'USD'
        else: log(f"⚠️ Could not detect EUR or USD. Defaulting to {DEFAULT_CURRENCY}.")
        log(f"Detected currency: {currency}")

        exchange_rate = fetch_exchange_rate(main_date_obj, currency)
        if exchange_rate is None:
            raise HTTPException(status_code=400, detail=f"לא נמצא שער המרה למטבע {currency} בתאריך {main_date_str}")
        log(f"Fetched exchange rate: {exchange_rate}")

        row_context = {}
        for idx, item in enumerate(service_items[:5], start=1):
            translated_desc = auto_translate(item["description"])
            if translated_desc is None:
                log(f"⚠️ Failed translating description: '{item['description']}'. Using original.")
                translated_desc = item["description"]
            
            row_context[f"RN{idx}"] = idx
            row_context[f"ServiceDescription{idx}"] = translated_desc
            row_context[f"ServiceDate{idx}"] = item.get("ServiceDate", "")
            row_context[f"Cur{idx}"] = currency
            row_context[f"Amount{idx}"] = f"{item['line_total']:.2f}"
            row_context[f"UnitPrice{idx}"] = f"{exchange_rate:.5f}"
            row_context[f"LineTotal{idx}"] = f"{round(item['line_total'] * exchange_rate, 2):.2f}"

        total_original = sum(item['line_total'] for item in service_items)
        vat_percent = DEFAULT_VAT_PERCENT
        base_bgn = round(total_original * exchange_rate, 2)
        vat_bgn = round(base_bgn * (vat_percent / 100), 2)
        total_bgn = base_bgn + vat_bgn
        
        invoice_number = f"{int(supplier_data.get('Last invoice number', 0)) + 1:08d}"
        df.loc[df["SupplierCompanyID"] == int(supplier_id), "Last invoice number"] = int(invoice_number)
        df.to_excel(SUPPLIERS_PATH, index=False)

        base_context = {
            "InvoiceNumber": invoice_number, "Date": main_date_str,
            "RecipientName": transliterate_to_bulgarian(customer_details['name']) or "N/A",
            "RecipientID": customer_details.get('id') or (customer_details['vat'].replace("BG","") if customer_details['vat'] else "N/A"),
            "RecipientVAT": customer_details['vat'] or "N/A",
            "RecipientAddress": transliterate_to_bulgarian(customer_details['address']) or "N/A",
            "RecipientCity": customer_details['city'] or "N/A", "RecipientCountry": customer_details['country'],
            "SupplierName": auto_translate(str(supplier_data["SupplierName"])),
            "SupplierCompanyID": str(supplier_data["SupplierCompanyID"]),
            "SupplierCompanyVAT": str(supplier_data["SupplierCompanyVAT"]),
            "SupplierAddress": auto_translate(str(supplier_data["SupplierAddress"])),
            "SupplierCity": auto_translate(str(supplier_data["SupplierCity"])),
            "SupplierContactPerson": str(supplier_data["SupplierContactPerson"]),
            "IBAN": str(supplier_data["IBAN"]), "BankName": auto_translate(str(supplier_data["Bankname"])), "BankCode": str(supplier_data["BankCode"]),
            "AmountBGN": f"{base_bgn:,.2f}".replace(",", "X").replace(".", ",").replace("X", " "),
            "VATAmount": f"{vat_bgn:,.2f}".replace(",", "X").replace(".", ",").replace("X", " "),
            "vat_percent": vat_percent,
            "TotalBGN": f"{total_bgn:,.2f}".replace(",", "X").replace(".", ",").replace("X", " "),
            "TotalInWords": number_to_bulgarian_words(total_bgn, as_words=True),
            "ExchangeRate": exchange_rate,
            "TransactionBasis": "По сметка", "TransactionCountry": "България"
        }
        
        template_path = get_template_path_by_rows(len(service_items))
        tpl = DocxTemplate(template_path)
        
        merged_context = {**base_context, **row_context}
        log(f"Rendering template '{template_path}' with final context.")
        
        tpl.render(merged_context)
        
        output_filename = f"bulgarian_invoice_{invoice_number}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)
        log(f"Invoice '{output_filename}' created.")
        
        drive_link = upload_to_drive(output_path, output_filename)
        
        return JSONResponse({"success": True, "data": {"invoice_number": invoice_number, "drive_link": drive_link}})

    except HTTPException as he:
        raise he
    except Exception as e:
        log(f"❌ GLOBAL EXCEPTION: {traceback.format_exc()}")
        return JSONResponse({"success": False, "error": f"An unexpected error occurred: {e}"}, status_code=500)
    
    finally:
        # ⭐️ IMPROVEMENT: Clean up temporary files
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
            log(f"Cleaned up input file: {file_path}")
        if 'output_path' in locals() and os.path.exists(output_path):
            os.remove(output_path)
            log(f"Cleaned up output file: {output_path}")
