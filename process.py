import os
import re
import datetime
import pandas as pd
import requests
import pytesseract
import traceback
from pdf2image import convert_from_path
from fastapi import UploadFile, APIRouter
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader
from xml.etree import ElementTree as ET
from docx import Document
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from tempfile import NamedTemporaryFile

# --- Constants and Setup ---
SUPPLIERS_PATH = "suppliers.xlsx"
TEMPLATE_PATH = "BulTrans_Template_FinalFInal.docx"
UPLOAD_DIR = "/tmp/uploads"
DRIVE_FOLDER_ID = "1JUTWRpBGKemiH6x89lHbV7b5J53fud3V"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter()

# --- Helper Functions (Preserved & Verified) ---

def log(msg):
    print(f"[{datetime.datetime.now()}] {msg}", flush=True)

def auto_translate(text, target_lang="bg"):
    if not text or not isinstance(text, str) or not text.strip(): return text
    try:
        if any('\u0400' <= char <= '\u04FF' for char in text): return text
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            log("⚠️ Missing GOOGLE_API_KEY. Skipping translation.")
            return text
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload = {"q": text, "target": target_lang}
        response = requests.post(url, json=payload, timeout=10)
        return response.json()["data"]["translations"][0]["translatedText"] if response.status_code == 200 else text
    except Exception as e:
        log(f"❌ Translation failed: {e}")
        return text

def transliterate_to_bulgarian(text):
    if not text: return ""
    table = { "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "кю", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "у", "x": "кс", "y": "й", "z": "з", "A": "А", "B": "Б", "C": "Ц", "D": "Д", "E": "Е", "F": "Ф", "G": "Г", "H": "Х", "I": "И", "J": "Дж", "K": "К", "L": "Л", "M": "М", "N": "Н", "O": "О", "P": "П", "Q": "Кю", "R": "Р", "S": "С", "T": "Т", "U": "У", "V": "В", "W": "У", "X": "Кс", "Y": "Й", "Z": "З", ".": ".", " ": " ", ",": ",", "-": "-", "&": "и"}
    return "".join(table.get(char, char) for char in text)

def number_to_bulgarian_words(amount, as_words=False):
    # ⭐️ FIXED: Removed .capitalize() to match test expectations
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
                        if ones > 0:
                            parts.append(f"{tens_word} и {word_map[ones]}")
                        else:
                            parts.append(tens_word)
                return " ".join(parts)
            leva_words = convert_to_words(leva)
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
        if response.status_code != 200: return 1.95583
        root = ET.fromstring(response.content)
        for row in root.findall(".//ROW"):
            if row.find("CODE").text == currency_code.upper():
                rate = float(row.find("RATE").text.replace(",", "."))
                ratio = float(row.find("RATIO").text.replace(",", "."))
                return rate / ratio
        return 1.95583
    except Exception as e:
        log(f"Exchange rate fetch failed: {e}. Defaulting.")
        return 1.95583

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json: raise ValueError("Missing GOOGLE_CREDS_JSON")
    with NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as tf:
        tf.write(creds_json)
        path = tf.name
    try:
        creds = service_account.Credentials.from_service_account_file(path, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    finally:
        os.remove(path)

def upload_to_drive(local_path, filename):
    log(f"Uploading '{filename}' to Google Drive...")
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
        log(f"❌ Google Drive upload failed: {e}")
        return None

# --- New, Improved & Test-Compatible Functions ---

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
    elif filename.lower().endswith((".doc", ".docx")):
        try:
            return "\n".join([p.text for p in Document(file_path).paragraphs])
        except Exception as e:
            log(f"DOCX extraction failed: {e}"); return ""
    return ""

def clean_number(num_str):
    # ⭐️ FIXED: Logic now handles both American (1,234.56) and European (1.234,56) formats.
    if not isinstance(num_str, str): return 0.0
    num_str = re.sub(r'[^\d\.,-]', '', num_str)
    if ',' in num_str and '.' in num_str:
        if num_str.rfind(',') > num_str.rfind('.'):
            # European format: 1.234,56 -> 1234.56
            num_str = num_str.replace('.', '').replace(',', '.')
        else:
            # American format: 1,234.56 -> 1234.56
            num_str = num_str.replace(',', '')
    elif ',' in num_str:
        # Assumes comma is decimal if it's the only separator
        num_str = num_str.replace(',', '.')
    try: return float(num_str)
    except: return 0.0

def extract_customer_details(text, supplier_name=""):
    details = {'name': '', 'vat': '', 'id': '', 'address': '', 'city': '', 'country': 'България'}
    lines = text.splitlines()
    for line in lines:
        line_lower = line.lower()
        if "customer name:" in line_lower and not details['name']:
            raw_name = line.split(':', 1)[1].strip()
            if supplier_name:
                raw_name = re.sub(re.escape(supplier_name), '', raw_name, flags=re.IGNORECASE)
            details['name'] = re.sub(r'(?i)\bsupplier\b', '', raw_name).strip()
        elif "vat no:" in line_lower and not details['vat']:
            vat_match = re.search(r'(BG\d+)', line, re.IGNORECASE)
            if vat_match: details['vat'] = vat_match.group(1)
        elif "id no:" in line_lower and not details['id']:
             id_match = re.search(r'\b(\d{9,})\b', line)
             if id_match: details['id'] = id_match.group(0)
        elif "address:" in line_lower and not details['address']:
            details['address'] = line.split(':', 1)[1].strip()
        elif "city:" in line_lower and not details['city']:
            city_name = line.split(':', 1)[1].strip()
            details['city'] = auto_translate(city_name)
    log(f"Found customer details: {details}")
    return details

def extract_service_lines(text):
    # ⭐️ FIXED: Logic now ignores footer keywords like 'subtotal'
    service_items, lines = [], text.splitlines()
    item_regex = re.compile(r"^(?P<desc>.+?)\s{2,}.*?(?P<total>[\d,]+\.\d{2})$")
    start_kw = ['description', 'descrizione', 'item', 'activity', 'amount']
    end_kw = ['subtotal', 'imponibile', 'total', 'thank you', 'tax']
    in_table = False
    for line in lines:
        line_lower = line.lower().strip()
        
        # Check for end of table first to stop processing
        if any(k in line_lower for k in end_kw):
            in_table = False
            continue

        # Check for start of table
        if any(k in line_lower for k in start_kw) and len(line_lower) < 50:
            in_table = True
            continue
        
        if in_table:
            match = item_regex.match(line.strip())
            if match:
                desc = match.group('desc').strip()
                # Additional check to ensure it's not a header-like line
                if desc.lower() not in start_kw and len(desc) > 3:
                    service_items.append({'description': desc, 'line_total': clean_number(match.group('total'))})
                    log(f"✅ Found structured line: {service_items[-1]}")

    if not service_items:
        log("No structured lines found. Falling back to generic description.")
        total = 0
        for p in [r'(?:Total|Totale|AMOUNT DUE)[\s:€$]*([\d,]+\.\d{2})']:
             m = re.findall(p, text, re.IGNORECASE)
             if m: total = clean_number(m[-1]); break
        if total > 0:
            service_items.append({'description': "Consulting services per invoice", 'line_total': total})
            log(f"✅ Created generic line from total: {total}")
    return service_items

# --- Compatibility Wrappers & Functions for Tests ---

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
    return "", None

def extract_customer_info(text, supplier_name=""):
    details = extract_customer_details(text, supplier_name)
    return {
        "RecipientName": transliterate_to_bulgarian(details.get('name')),
        "RecipientID": details.get('id') or (details.get('vat', '').replace("BG", "")),
        "RecipientVAT": details.get('vat'),
        "RecipientAddress": transliterate_to_bulgarian(details.get('address')),
        "RecipientCity": details.get('city'),
        "RecipientCountry": details.get('country'),
        "ServiceDescription": "", "RN": 1,
    }

def safe_extract_float(text):
    return clean_number(text)

def extract_amount(text):
    items = extract_service_lines(text)
    return sum(item['line_total'] for item in items) if items else 0.0

# --- Main Endpoint ---

@router.post("/process-invoice/")
async def process_invoice_upload(supplier_id: str, file: UploadFile):
    try:
        log(f"--- Starting invoice processing for supplier: {supplier_id}, file: {file.filename} ---")
        file_path = f"/tmp/{file.filename}"
        with open(file_path, "wb") as f: f.write(await file.read())
        text = extract_text_from_file(file_path, file.filename)
        if not text: raise HTTPException(status_code=400, detail="Could not extract text from file.")

        df = pd.read_excel(SUPPLIERS_PATH)
        supplier_row = df[df["SupplierCompanyID"] == int(supplier_id)]
        if supplier_row.empty: raise HTTPException(status_code=404, detail="Supplier not found")
        supplier_data = supplier_row.iloc[0]

        customer_details = extract_customer_details(text, supplier_data["SupplierName"])
        service_items = extract_service_lines(text)
        main_date_str, main_date_obj = extract_invoice_date(text)
        
        if not main_date_obj:
            main_date_obj = datetime.datetime.now()
            main_date_str = main_date_obj.strftime("%d.%m.%Y")
        
        if not service_items: raise HTTPException(status_code=400, detail="Could not find any service lines.")
        
        currency = 'EUR'
        if '€' in text or 'EUR' in text.upper(): currency = 'EUR'
        elif '$' in text or 'USD' in text.upper(): currency = 'USD'
        
        exchange_rate = fetch_exchange_rate(main_date_obj, currency)
        
        final_service_lines = []
        total_original = sum(item['line_total'] for item in service_items)
        for i, item in enumerate(service_items):
            final_service_lines.append({
                'RN': i + 1, 'ServiceDescription': auto_translate(item['description']), 'Cur': currency,
                'Amount': f"{item['line_total']:.2f}",
                'UnitPrice': f"{exchange_rate:.5f}",
                'LineTotal': round(item['line_total'] * exchange_rate, 2)
            })

        vat_percent = 20.0
        base_bgn = round(total_original * exchange_rate, 2)
        vat_bgn = round(base_bgn * (vat_percent / 100), 2)
        total_bgn = base_bgn + vat_bgn
        
        invoice_number = f"{int(supplier_data.get('Last invoice number', 0)) + 1:08d}"
        df.loc[df["SupplierCompanyID"] == int(supplier_id), "Last invoice number"] = int(invoice_number)
        df.to_excel(SUPPLIERS_PATH, index=False)

        context = {
            "service_lines": final_service_lines, "InvoiceNumber": invoice_number, "Date": main_date_str,
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

        tpl = DocxTemplate(TEMPLATE_PATH)
        tpl.render(context)
        output_filename = f"bulgarian_invoice_{invoice_number}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)
        log(f"Invoice '{output_filename}' created.")
        
        drive_link = upload_to_drive(output_path, output_filename)
        
        return JSONResponse({"success": True, "data": {"invoice_number": invoice_number, "drive_link": drive_link}})

    except Exception as e:
        log(f"❌ GLOBAL EXCEPTION: {traceback.format_exc()}")
        return JSONResponse({"success": False, "error": f"An unexpected error occurred: {e}"}, status_code=500)
