from fastapi import FastAPI, UploadFile
from process import process_invoice_upload
from fastapi.responses import JSONResponse
from fastapi import UploadFile, File, Form

app = FastAPI()

@app.post("/process-invoice")
async def generate_invoice(
    client_id: int = Form(...),
    file: UploadFile = File(...),
    template: UploadFile = File(...)
):
    return await process_invoice_upload(client_id, file, template)
