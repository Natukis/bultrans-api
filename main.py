from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from process import process_invoice_upload

app = FastAPI()

@app.post("/process-invoice/")
async def generate_invoice(
    supplier_id: int = Form(...),
    file: UploadFile = File(...),
    template: UploadFile = File(...)
):
    return await process_invoice_upload(supplier_id, file, template)
