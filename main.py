from fastapi import FastAPI
from process import process_invoice
from pydantic import BaseModel

app = FastAPI()

class InvoiceRequest(BaseModel):
    file_url: str
    template_path: str
    client_id: str

@app.post("/process-invoice")
def process_invoice_api(req: InvoiceRequest):
    return process_invoice(req.file_url, req.template_path, req.client_id)
