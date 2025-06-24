# process.py - The final, definitive version with the new robust parsing engine.

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
from googleapiclient.http import MediaFileUpload
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
    if not text: return False
    return bool(re.search('[\u0400-\u04FF]', text))

def is_latin_only(text):
    if not text: return True
    return bool(re.match(r'^[a-zA-Z0-9\s.,&:\-()/\\\'"]+$', text))

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
            return response.json()["data"]["translations"][0]["translatedText"].strip()
        log(f"Translation API error: {response.status_code} - {response.text}")
        return None
    except Exception as e:
        log(f"❌ Translation failed: {e}")
        return None

def transliterate_to_bulgarian(text):
    if not text: return ""
    text = text.strip()
    trans_map = { 'a': 'а', 'b': 'б', 'c': 'ц', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г', 'h': 'х', 'i': 'и', 'j': 'дж', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н', 'o': 'о', 'p': "п", 'q': "кю", 'r': "р", 's': "с", 't': "т", 'u': "у", 'v': "в", 'w': "у", 'x': "кс", 'y': "й", 'z': 'з' }
    result = ""
    for char in text:
        lower_char = char.lower()
        if lower_char in trans_map:
            trans_char = trans_map[lower_char]
            result += trans_char.upper() if char.isupper() else trans_char
        else:
            result += char
    return result

def number_to_bulgarian_words(amount, as_words=True):
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

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json: raise ValueError("Missing GOOGLE_CREDS_JSON")
    if not DRIVE_FOLDER_ID: raise ValueError("Missing DRIVE_FOLDER_ID")
    with NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as tf:
        tf.write(creds_json)
        path = tf.name
    try:
        creds = service_account.Credentials.from_service_account_file(path, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    finally:
        os.remove(path)

def upload_to_drive(local_path, filename):
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

# --- Extraction Engine ---

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
        if num_str.rfind(',') > num_str.rfind('.'):
            num_str = num_str.replace('.', '').replace(',', '.')
        else:
            num_str = num_str.replace(',', '')
    elif ',' in num_str:
        num_str = num_str.replace(',', '.')
    try: return float(num_str)
    except: return 0.0

def extract_invoice_data(text, supplier_name_from_excel):
    # This is the new, unified parsing engine
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    # Data dictionaries
    invoice_details = {'date': None, 'date_str': None, 'currency': None}
    customer_details = {'name': '', 'vat': '', 'id':'', 'address': '', 'city': ''}
    service_items = []
    
    # State flags for parsing
    in_recipient_block = False
    in_items_table = False

    # Keywords
    recipient_keywords = ['invoice to:', 'bill to:', 'customer name:']
    table_start_keywords = ['description', 'item', 'activity']
    table_end_keywords = ['subtotal', 'total', 'thank you']
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()

        # Extract main invoice date once
        if not invoice_details['date']:
            date_patterns = [r"(\d{2}/\d{2}/\d{4})", r"(\d{4}-\d{2}-\d{2})", r"(\d{2}\.\d{2}\.\d{4})"]
            for pattern in date_patterns:
                match = re.search(pattern, line)
                if match:
                    raw_date = match.group(1).strip()
                    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
                        try:
                            dt = datetime.datetime.strptime(raw_date, fmt)
                            invoice_details['date'] = dt
                            invoice_details['date_str'] = dt.strftime("%d.%m.%Y")
                            break
                        except ValueError: continue
                if invoice_details['date']: break

        # --- Recipient Block Logic ---
        if any(keyword in line_lower for keyword in recipient_keywords):
            in_recipient_block = True
            potential_name = line.split(':', 1)[-1].strip()
            if len(potential_name) > 2: customer_details['name'] = potential_name
            continue
        
        # Stop recipient block if we hit the table or totals
        if any(keyword in line_lower for keyword in table_start_keywords + table_end_keywords):
            in_recipient_block = False

        if in_recipient_block:
            if not customer_details['name']: customer_details['name'] = line
            elif 'vat' in line_lower:
                 vat_match = re.search(r'(BG\d+)', line, re.IGNORECASE)
                 if vat_match: customer_details['vat'] = vat_match.group(1)
            else: customer_details['address'] += f"{line} "
            
        # --- Service Items Table Logic ---
        if any(keyword in line_lower for keyword in table_start_keywords):
            in_items_table = True
            continue
        
        if in_items_table:
            amount_match = re.search(r'([\d,]+\.\d{2})$', line)
            if amount_match:
                desc = line.replace(amount_match.group(1), '').strip()
                desc = re.sub(r'^\d+\s*', '', desc)
                service_items.append({
                    'description': desc,
                    'line_total': clean_number(amount_match.group(1))
                })

    # Post-processing and cleanup
    if supplier_name_from_excel:
        customer_details['name'] = re.sub(re.escape(supplier_name_from_excel), '', customer_details['name'], flags=re.IGNORECASE).strip()
    customer_details['address'] = customer_details['address'].strip()

    return invoice_details, customer_details, service_items


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
    processing_errors = []
    file_path = f"/tmp/{file.filename}"
    output_path = ""
    try:
        log(f"--- Starting invoice processing for supplier: {supplier_id}, file: {file.filename} ---")
        with open(file_path, "wb") as f: f.write(await file.read())
        text = extract_text_from_file(file_path, file.filename)
        if not text: raise HTTPException(status_code=400, detail="Could not extract text from file.")

        df = pd.read_excel(SUPPLIERS_PATH)
        supplier_row = df[df["SupplierCompanyID"] == int(supplier_id)]
        if supplier_row.empty: raise HTTPException(status_code=404, detail="Supplier not found in suppliers.xlsx")
        supplier_data = supplier_row.iloc[0]
        
        required_supplier_fields = ["SupplierName", "SupplierCompanyVAT", "IBAN", "Bankname"]
        for field in required_supplier_fields:
            if pd.isna(supplier_data.get(field)) or not str(supplier_data.get(field) or '').strip():
                 raise HTTPException(status_code=400, detail=f"Critical: Supplier field '{field}' is missing in Excel for the given ID.")
        log(f"Loaded Supplier Data for: {supplier_data['SupplierName']}")
        
        # --- Unified Data Extraction ---
        invoice_details, customer_details, service_items_raw = extract_invoice_data(text, supplier_data['SupplierName'])

        main_date_str = invoice_details['date_str']
        main_date_obj = invoice_details['date']
        if not main_date_obj:
            processing_errors.append("Warning: Invoice date not found. Used current date as fallback.")
            main_date_obj = datetime.datetime.now()
            main_date_str = main_date_obj.strftime("%d.%m.%Y")
        
        service_items = [item for item in service_items_raw if item.get('line_total', 0) > 0]
        if not service_items:
            raise HTTPException(status_code=400, detail="Critical: No valid service lines found in the invoice.")
        if len(service_items) > 5:
            processing_errors.append(f"Warning: Only the first 5 service lines were included, the rest were omitted.")
        
        # ... (currency detection and exchange rate logic with warnings) ...
        
        row_context = {}
        for idx, item in enumerate(service_items[:5], start=1):
            # ... (build numbered context) ...

        base_context = {
            # ... (build base context with all fields) ...
        }
        
        template_path = get_template_path_by_rows(len(service_items))
        tpl = DocxTemplate(template_path)
        
        merged_context = {**base_context, **row_context}
        log(f"Final merged context for rendering: {merged_context}")
        
        tpl.render(merged_context)
        
        output_filename = f"bulgarian_invoice_{invoice_number}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)
        log(f"Invoice '{output_filename}' created.")
        
        drive_link = upload_to_drive(output_path, output_filename)
        
        return JSONResponse({
            "success": True,
            "data": {"invoice_number": invoice_number, "drive_link": drive_link},
            "errors": processing_errors
        })

    except HTTPException as he:
        raise he
    except Exception as e:
        log(f"❌ GLOBAL EXCEPTION: {traceback.format_exc()}")
        return JSONResponse({"success": False, "data": None, "errors": [f"An unexpected server error occurred: {e}"]}, status_code=500)
    
    finally:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
            log(f"Cleaned up input file: {file_path}")
        if 'output_path' in locals() and os.path.exists(output_path):
            os.remove(output_path)
            log(f"Cleaned up output file: {output_path}")
