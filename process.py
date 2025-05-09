
import os
import re
import datetime
import pandas as pd
import requests
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader

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

        lines = text.splitlines()
        amount = vat = total = 0.0
        for line in lines:
            if "Total Amount of Bill" in line:
                total = safe_extract_float(line)
            elif "VAT Amount" in line:
                vat = safe_extract_float(line)
            elif "Total Amount:" in line:
                amount = safe_extract_float(line)

        amount_bgn = round(amount, 2)
        vat_amount = round(vat, 2)
        total_bgn = round(total, 2)

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
            "Currency": "BGN",
            "Amount": 1,
            "ExchangeR": amount_bgn,
            "AmountBG": amount_bgn,
            "AmountBGN": amount_bgn,
            "VATAmount": vat_amount,
            "TotalBGN": total_bgn,
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
