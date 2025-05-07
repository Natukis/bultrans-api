import os
import re
import datetime
import pandas as pd
from fastapi import UploadFile
from fastapi.responses import JSONResponse
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader

UPLOAD_DIR = "/tmp/uploads"
CLIENT_TABLE_PATH = "/etc/secrets/clients.xlsx"

os.makedirs(UPLOAD_DIR, exist_ok=True)

def extract_field(pattern, text, default=""):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default

def translate(text):
    return text

def get_exchange_rate(date_str, currency):
    try:
        return 1.95583  # קבוע לבינתיים
    except:
        return 1.95583

async def process_invoice(client_id: str, file: UploadFile, template: UploadFile):
    try:
        invoice_path = os.path.join(UPLOAD_DIR, file.filename)
        template_path = os.path.join(UPLOAD_DIR, template.filename)

        with open(invoice_path, "wb") as f:
            f.write(await file.read())
        with open(template_path, "wb") as f:
            f.write(await template.read())

        reader = PdfReader(invoice_path)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

        clients = pd.read_excel(CLIENT_TABLE_PATH)
        client_row = clients[clients["Company ID"] == int(client_id)]
        if client_row.empty:
            return JSONResponse(content={"success": False, "error": "Client not found"})

        invoice_number = str(int(client_row["Last invoice number"].values[0]) + 1).zfill(10)
        invoice_date = extract_field(r"Date:\s*([\d/\.]+)", text).replace("/", ".")

        match = re.search(r"Total Amount of Bill:\s*([A-Z]{3})\s*([\d\.,]+)", text)
        currency, amount = (match.group(1), float(match.group(2).replace(",", ""))) if match else ("EUR", 0)

        exchange_rate = get_exchange_rate(invoice_date, currency)
        amount_bgn = round(amount * exchange_rate, 2)

        data = {
            "InvoiceNumber": invoice_number,
            "Date": invoice_date,
            "CustomerName": extract_field(r"Customer Name:\s*(.+)", text),
            "SupplierName": extract_field(r"Supplier:\s*(.+)", text),
            "Amount": amount,
            "AmountBGN": amount_bgn,
            "ExchangeRate": exchange_rate,
            "Currency": currency,
            "IBAN": client_row["IBAN"].values[0],
            "BankName": client_row["Bank name"].values[0],
        }

        save_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
        doc = DocxTemplate(template_path)
        doc.render(data)
        doc.save(save_path)

        return JSONResponse(content={
            "success": True,
            "invoice_number": invoice_number,
            "file_path": save_path
        })

    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})
