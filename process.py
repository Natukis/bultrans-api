
import os
import re
import requests
import datetime
import pandas as pd
from docxtpl import DocxTemplate
from PyPDF2 import PdfReader

CLIENT_TABLE_PATH = "clients.xlsx"

def extract_field(pattern, text, default=""):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default

def translate(text):
    return text  # placeholder for now

def get_exchange_rate(date_str, currency):
    try:
        date = datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
        response = requests.get("https://www.bnb.bg/Statistics/StExternalSector/StExchangeRates/StERForeignCurrencies/index.htm?download=xml")
        if response.ok:
            return 1.95583  # placeholder rate
    except:
        pass
    return 1.95583

def process_invoice(file_url, template_path, client_id):
    try:
        invoice_path = "/tmp/invoice.pdf"
        tpl_path = "/tmp/template.docx"
        with open(invoice_path, 'wb') as f: f.write(requests.get(file_url).content)
        with open(tpl_path, 'wb') as f: f.write(requests.get(template_path).content)

        reader = PdfReader(invoice_path)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

        clients = pd.read_excel(CLIENT_TABLE_PATH)
        client_row = clients[clients["Company ID"] == int(client_id)]
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

        save_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
        doc = DocxTemplate(tpl_path)
        doc.render(data)
        doc.save(save_path)
openpyxl==3.1.2

        return {"success": True, "invoice_number": invoice_number, "file_path": save_path}
    except Exception as e:
        return {"success": False, "error": str(e)}
