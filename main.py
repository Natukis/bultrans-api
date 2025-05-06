
from fastapi import FastAPI
from pydantic import BaseModel
from process import process_invoice

app = FastAPI()

class InvoiceRequest(BaseModel):
    file_url: str
    template_path: str
    client_id: str

@app.post("/process-invoice")
async def process_invoice_api(req: InvoiceRequest):
    result = process_invoice(req.file_url, req.template_path, req.client_id)
    return result
