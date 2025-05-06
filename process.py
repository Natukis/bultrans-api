import os
import re
import requests
import datetime
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader

CLIENT_TABLE_PATH = "clients.xlsx"  # נמצא בתיקייה הראשית של הפרויקט ב-Render

app = FastAPI()


class InvoiceRequest(BaseModel):
    file_url: str
    template_path: str
    client_id: str


def extract_field(pattern, text, default=""):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default


def translate(text):
    return text  # placeholder


def get_exchange_rate(date_str, currency):
    try:
        date = datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
        # TODO: Implement real exchange rate logic
        return 1.95583  # Fixed BGN rate for EUR
    except:
        return 1.95583


@app.post("/process-invoice")
def process_invoice_api(request: InvoiceRequest):
    try:
        invoice_path = "/tmp/invoice.pdf"
        tpl_path = "/tmp/template.docx"

        with open(invoice_path, 'wb') as f:
            f.write(requests.get(request.file_url).content)

        with open(tpl_path, 'wb') as f:
            f.write(requests.get(request.template_path).content)

        reader = PdfReader(invoice_path)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

        clients = pd.read_excel(CLIENT_TABLE_PATH)
        client_row = clients[clients["Company ID"] == int(request.client_id)]
        if client_row.empty:
            return {"success": False, "error": "Client not found"}

        invoice_number = str(int(client_row["Last invoice number"].values[0]) + 1).zfill(10)
        invoice_date = extract_field(r"Date:\s*([\d/\.]+)", text).replace("/", ".")

        match = re.search(r"Total Amount of Bill:\s*([A-Z]{3})\s*([\d\.,]+)", text)
        currency, amount = (match.group(1), float(match.group(2).replace(',', ''))) if match else ("EUR", 0)

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

        output_name = f"bulgarian_invoice_{invoice_number}.docx"
        output_path = f"/tmp/{output_name}"

        doc = DocxTemplate(tpl_path)
        doc.render(data)
        doc.save(output_path)

        return {
            "success": True,
            "invoice_number": invoice_number,
            "file_path": f"/tmp/{output_name}",
            "download_url": f"/download/{output_name}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = f"/tmp/{filename}"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', filename=filename)
