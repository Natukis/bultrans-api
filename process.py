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

# --- Configuration ---
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

def auto_translate(text, target_lang="bg"):
    if not text or not isinstance(text, str) or not text.strip() or is_cyrillic(text):
        return text
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        log("Warning: GOOGLE_API_KEY not set. Cannot translate.")
        return text
    try:
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload = {"q": text, "target": target_lang}
        response = requests.post(url, json=payload, timeout=GOOGLE_API_TIMEOUT)
        if response.ok:
            return response.json()["data"]["translations"][0]["translatedText"].strip()
        else:
            log(f"Translation API error: {response.status_code} - {response.text}")
            return text
    except Exception as e:
        log(f"❌ Translation failed: {e}")
        return text

def transliterate_to_bulgarian(text):
    if not text: return ""
    text = text.strip()
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
        "Y": "Й", "Z": "З"
    }
    # First, handle common suffixes
    text = re.sub(r'(?i)\bLTD\b', 'ЛТД', text)
    text = re.sub(r'(?i)\bEOOD\b', 'ЕООД', text)
    text = re.sub(r'(?i)\bOOD\b', 'ООД', text)
    
    return "".join(table.get(char, char) for char in text)

def number_to_bulgarian_words(amount):
    try:
        leva = int(amount)
        stotinki = int(round((amount - leva) * 100))
        word_map = {0: "нула", 1: "един", 2: "два", 3: "три", 4: "четири", 5: "пет", 6: "шест", 7: "седем", 8: "осем", 9: "девет", 10: "десет", 11: "единадесет", 12: "дванадесет", 13: "тринадесет", 14: "четиринадесет", 15: "петнадесет", 16: "шестнадесет", 17: "седемнадесет", 18: "осемнадесет", 19: "деветнадесет", 20: "двадесет", 30: "тридесет", 40: "четиридесет", 50: "петдесет", 60: "шестдесет", 70: "седемдесет", 80: "осемдесет", 90: "деветдесет"}
        def convert(n):
            if n in word_map: return word_map[n]
            parts = []
            if n >= 1000:
                thousands = n // 1000
                parts.append(f"{'хиляда' if thousands == 1 else (convert(thousands) + ' хиляди')}")
                n %= 1000
            if n >= 100:
                hundreds_map = {1: "сто", 2: "двеста", 3: "триста", 4: "четиристотин", 5: "петстотин", 6: "шестстотин", 7: "седемстотин", 8: "осемстотин", 9: "деветстотин"}
                parts.append(hundreds_map[n // 100])
                n %= 100
            if n > 0:
                if parts: parts.append("и")
                if n <= 20: parts.append(word_map[n])
                else:
                    tens_word = word_map[n // 10 * 10]
                    ones_word = word_map.get(n % 10, "")
                    parts.append(f"{tens_word}{' и ' + ones_word if ones_word else ''}")
            return " ".join(parts)
        leva_words = convert(leva)
        return f"{leva_words} лева и {stotinki:02d} стотинки"
    except Exception as e:
        log(f"Error in number_to_bulgarian_words: {e}")
        return ""

def extract_text_from_file(file_path, filename):
    log(f"Extracting text from '{filename}'")
    if filename.lower().endswith(".pdf"):
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(file_path).pages)
            if len(text.strip()) > 50: return text
            log("Fallback to OCR for PDF.")
            return "\n".join(pytesseract.image_to_string(img, config='--psm 6') for img in convert_from_path(file_path, dpi=300))
        except Exception as e:
            log(f"PDF extraction failed: {e}")
            return ""
    return ""

def extract_invoice_date(text):
    patterns = [r"(\d{2}[/.-]\d{2}[/.-]\d{4})", r"(\d{4}[/.-]\d{2}[/.-]\d{2})", r"(\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s\d{1,2},?\s\d{4})"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw_date = match.group(1).replace(",", "").replace("/", ".").replace("-", ".")
            for fmt in ("%d.%m.%Y", "%Y.%m.%d", "%B %d %Y"):
                try:
                    return datetime.datetime.strptime(raw_date, fmt)
                except ValueError:
                    continue
    return None

def extract_service_lines(text):
    """
    מחזירה רשימה של שורות שירות בפורמט:
    [{'description': ..., 'line_total': ..., 'service_date': datetime|None}]
    """
    service_items = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    header_idx, footer_idx = -1, len(lines)
    for i, line in enumerate(lines):
        if re.search(r'(?i)\b(Description|Item|Услуга)\b', line) and len(line) < 50:
            header_idx = i
        if re.search(r'(?i)\b(subtotal|total|общо|ддс|vat|tax)\b', line):
            footer_idx = i
            break
    if header_idx != -1:
        for line in lines[header_idx + 1:footer_idx]:
            m = re.search(r'([\d\s,]+\.?\d*)$', line)
            if m and len(line[:m.start()].strip()) > 3:
                try:
                    amount_str = m.group(1).replace(" ", "").replace(",", "")
                    amount = float(amount_str)
                    desc = line[:m.start()].strip()

                    # חפש תאריך בתוך התיאור
                    date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', desc)
                    service_date = None
                    if date_match:
                        try:
                            service_date = datetime.datetime.strptime(date_match.group(1), "%d.%m.%Y")
                        except ValueError:
                            pass

                    service_items.append({
                        'description': desc,
                        'line_total': amount,
                        'service_date': service_date
                    })
                except ValueError:
                    continue
    if not service_items:
        log("No service table found.")
    return service_items

def extract_recipient_details(text: str, supplier_data: pd.Series) -> dict:
    log("--- Starting Hybrid Recipient Details Extraction (V-Final) ---")
    details = {'name': '', 'vat': '', 'id': '', 'address': ''}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    supplier_vat = str(supplier_data.get("SupplierCompanyVAT", "###NEVER_FIND_THIS###"))

    # --- Method 1: Direct Keyword Search (The "Old Code" Magic) ---
    log("Attempting Method 1: Direct Keyword Search...")
    customer_keywords = ['customer name:', 'bill to:', 'invoice to:', 'invoice for:', 'client:', 'получател:', 'клиент:']
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for keyword in customer_keywords:
            if keyword in line_lower:
                log(f"Method 1 SUCCESS: Found keyword '{keyword}' on line {i}.")
                potential_name = re.split(keyword, line, flags=re.IGNORECASE)[-1].strip()
                if not potential_name and i + 1 < len(lines):
                    potential_name = lines[i+1].strip()
                if potential_name:
                    details['name'] = potential_name
                    for j in range(i + 1, min(i + 7, len(lines))):
                        sub_line = lines[j]
                        if sub_line.strip() == details['name']: continue
                        sub_line_lower = sub_line.lower()
                        if not details['address'] and any(kw in sub_line_lower for kw in ['address', 'ул.', 'бул.', 'str.']):
                            details['address'] = sub_line.split(':', 1)[-1].strip()
                        if not details['vat']:
                            m = re.search(r'\b([A-Z]{2}\s?[0-9\s-]{8,13})\b', sub_line)
                            if m and m.group(1) != supplier_vat: details['vat'] = m.group(1)
                        if not details['id'] and any(kw in sub_line_lower for kw in ['eik', 'id no']):
                            id_match = re.search(r'\d{9,}', sub_line)
                            if id_match: details['id'] = id_match.group(0)
                    log(f"Method 1 extracted: {details}")
                    return details

    # --- Method 2: Block Isolation Fallback (The "New" Smart Method) ---
    log("Method 1 FAILED. Trying Method 2: Block Isolation Fallback.")
    blocks = [b.strip() for b in text.split('\n\n') if b.strip()]
    non_supplier_blocks = [b for b in blocks if supplier_vat not in b]
    for block in non_supplier_blocks:
        if '\n' in block and len(block) > 20 and any(char.isdigit() for char in block):
            log(f"Fallback: Found candidate block:\n{block}")
            block_lines = [ln.strip() for ln in block.split('\n')]
            details['name'] = block_lines[0]
            for line in block_lines[1:]:
                if not details['address'] and any(kw in line.lower() for kw in ['ул.', 'бул.', 'str.']): details['address'] = line
                if not details['vat'] and 'vat' in line.lower():
                    m = re.search(r'\b([A-Z]{2}\s?[0-9\s-]{8,13})\b', line)
                    if m and m.group(1) != supplier_vat: details['vat'] = m.group(1)
                if not details['id'] and 'eik' in line.lower():
                    id_match = re.search(r'\d{9,}', line)
                    if id_match: details['id'] = id_match.group(0)
            log(f"Method 2 extracted: {details}")
            return details

    log("All methods failed to find recipient details.")
    return details

def get_template_path_by_rows(num_rows: int) -> str:
    effective_rows = min(num_rows, 5) if num_rows > 0 else 1
    path = os.path.join(TEMPLATES_DIR, f"BulTrans_Template_{effective_rows}row.docx")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Template file not found: {path}")
    return path

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json: raise ValueError("Missing GOOGLE_CREDS_JSON")
    with NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as tf:
        tf.write(creds_json); path = tf.name
    try:
        creds = service_account.Credentials.from_service_account_file(path, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    finally: os.remove(path)

def upload_to_drive(local_path, filename):
    log(f"Uploading '{filename}' to Google Drive...")
    service = get_drive_service()
    file_metadata = {"name": filename, "parents": [os.getenv("DRIVE_FOLDER_ID")]}
    media = MediaFileUpload(local_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    service.permissions().create(fileId=file["id"], body={"type": "anyone", "role": "reader"}).execute()
    link = file.get("webViewLink")
    log(f"Successfully uploaded. Link: {link}")
    return link

# --- Main API Endpoint ---
def get_bnb_exchange_rate(date_obj):
    """
    מחזיר את שער ההמרה BNB ל־BGN עבור EUR בתאריך הנתון.
    """
    url = f"https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?downloadOper=&group1=first&date={date_obj.strftime('%d.%m.%Y')}&search="
    log(f"Fetching BNB exchange rate for date {date_obj.strftime('%d.%m.%Y')}")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        html = resp.text
        m = re.search(r"<td>EUR</td>\s*<td>([\d,.]+)</td>", html)
        if m:
            rate_str = m.group(1).replace(",", ".")
            rate = float(rate_str)
            log(f"BNB exchange rate for EUR: {rate}")
            return rate
        else:
            raise ValueError("EUR exchange rate not found on BNB site.")
    except Exception as e:
        log(f"❌ Failed to fetch BNB exchange rate: {e}")
        raise


@router.post("/process-invoice/")
async def process_invoice_upload(supplier_id: str, file: UploadFile):
    processing_errors = []
    file_path = f"/tmp/{file.filename}"
    try:
        with open(file_path, "wb") as f: f.write(await file.read())
        text = extract_text_from_file(file_path, file.filename)
        if not text: raise HTTPException(status_code=400, detail="Could not extract text from file.")

        df = pd.read_excel(SUPPLIERS_PATH, dtype={'SupplierCompanyID': str})
        supplier_row = df[df["SupplierCompanyID"] == str(supplier_id)]
        if supplier_row.empty: raise HTTPException(status_code=404, detail=f"Supplier with ID '{supplier_id}' not found.")
        supplier_data = supplier_row.iloc[0]
        log(f"Loaded Supplier Data for: {supplier_data['SupplierName']}")
        iban = str(supplier_data["IBAN"]).strip()
        if not iban:
            raise HTTPException(status_code=400, detail=f"Missing IBAN for supplier {supplier_data['SupplierName']}.")
        
        # בדוק אם ה־IBAN מופיע פעמיים בקובץ
        if df["IBAN"].value_counts().get(iban, 0) > 1:
            raise HTTPException(status_code=400, detail=f"Duplicate IBAN detected for supplier {supplier_data['SupplierName']}.")

        date_obj = extract_invoice_date(text) or datetime.datetime.now()
        service_items = extract_service_lines(text)
        max_supported_rows = 5
        if len(service_items) > max_supported_rows:
            raise HTTPException(status_code=400, detail=f"Too many service lines ({len(service_items)}) — maximum supported is {max_supported_rows}.")

        if not service_items:     
            raise HTTPException(status_code=400, detail="No service lines found in the invoice.")
        customer_details = extract_recipient_details(text, supplier_data)
        if not customer_details.get('name'): processing_errors.append("Warning: Could not identify recipient details.")

        exchange_rate = get_bnb_exchange_rate(date_obj)
        base_bgn = sum(item['line_total'] for item in service_items) * exchange_rate
        vat_bgn = base_bgn * (DEFAULT_VAT_PERCENT / 100)
        total_bgn = base_bgn + vat_bgn
        
        last_invoice_num = int(supplier_data.get('Last invoice number', 0))
        invoice_number = f"{last_invoice_num + 1:010d}"
        
        def format_bgn(amount): return f"{amount:,.2f}".replace(",", " ").replace(".", ",")
        
        recipient_name_raw = customer_details.get('name', '')
        if not recipient_name_raw:
            raise HTTPException(status_code=400, detail="Recipient name could not be identified.")
        elif is_cyrillic(recipient_name_raw):
            recipient_name_final = recipient_name_raw
        else:
            log(f"Recipient name '{recipient_name_raw}' is in Latin script. Transliterating.")
            recipient_name_final = transliterate_to_bulgarian(recipient_name_raw)


        row_context = {}
        for idx, item in enumerate(service_items[:5], start=1):
            row_context[f"RN{idx}"] = idx
            row_context[f"ServiceDescription{idx}"] = item['description']
            row_context[f"Cur{idx}"] = "EUR"
            row_context[f"Amount{idx}"] = f"{item['line_total']:.2f}"
            row_context[f"UnitPrice{idx}"] = f"{exchange_rate:.5f}"
            row_context[f"LineTotal{idx}"] = format_bgn(round(item['line_total'] * exchange_rate, 2))

        base_context = {
            "InvoiceNumber": invoice_number,
            "Date": date_obj.strftime("%d.%m.%Y"),
            "RecipientName": recipient_name_final,
            "RecipientID": customer_details.get('id', ''),
            "RecipientVAT": customer_details.get('vat', ''),
            "RecipientAddress": auto_translate(customer_details.get('address', '')),
            "SupplierName": auto_translate(str(supplier_data["SupplierName"])),
            "SupplierCompanyID": str(supplier_data["SupplierCompanyID"]),
            "SupplierCompanyVAT": str(supplier_data["SupplierCompanyVAT"]),
            "SupplierAddress": auto_translate(str(supplier_data["SupplierAddress"])),
            "SupplierCity": auto_translate(str(supplier_data["SupplierCity"])),
            "SupplierContactPerson": str(supplier_data["SupplierContactPerson"]),
            "IBAN": str(supplier_data["IBAN"]),
            "BankName": auto_translate(str(supplier_data["Bankname"])),
            "BankCode": str(supplier_data.get("BankCode", "")),
            "AmountBGN": format_bgn(base_bgn),
            "VATAmount": format_bgn(vat_bgn),
            "vat_percent": int(DEFAULT_VAT_PERCENT),
            "TotalBGN": format_bgn(total_bgn),
            "TotalInWords": number_to_bulgarian_words(total_bgn),
            "ExchangeRate": f"{exchange_rate:.5f}",
            "TransactionBasis": auto_translate(str(supplier_data["SupplierContactPerson"])) or "По сметка"
        }
        
        template_path = get_template_path_by_rows(len(service_items))
        tpl = DocxTemplate(template_path)
        tpl.render({**base_context, **row_context})
        
        output_filename = f"bulgarian_invoice_{invoice_number}.docx"
        output_path = f"/tmp/{output_filename}"
        tpl.save(output_path)
        log(f"Invoice '{output_filename}' created locally.")
        
        df.loc[df["SupplierCompanyID"] == str(supplier_id), "Last invoice number"] = int(invoice_number)
        df.to_excel(SUPPLIERS_PATH, index=False)
        drive_link = upload_to_drive(output_path, output_filename)
        
        return JSONResponse({
            "success": True, 
            "data": {"invoice_number": invoice_number, "drive_link": drive_link}, 
            "errors": processing_errors
        })

    except Exception as e:
        log(f"❌ GLOBAL EXCEPTION: {traceback.format_exc()}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        if 'file_path' in locals() and os.path.exists(file_path): os.remove(file_path)
        if 'output_path' in locals() and os.path.exists(output_path): os.remove(output_path)
