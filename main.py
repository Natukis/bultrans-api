from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from process import process_invoice_upload
import os

app = FastAPI()

# יצירת החשבונית מקובץ PDF/Word + תבנית Word
@app.post("/process-invoice")
async def generate_invoice(
    client_id: int = Form(...),
    file: UploadFile = File(...),
    template: UploadFile = File(...)
):
    return await process_invoice_upload(client_id, file, template)

# הורדת הקובץ שנוצר לפי מספר חשבונית
@app.get("/download-invoice/{invoice_number}")
def download_invoice(invoice_number: str):
    file_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
    if not os.path.exists(file_path):
        return {"success": False, "error": "File not found"}
    return FileResponse(
        file_path,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        filename=f"bulgarian_invoice_{invoice_number}.docx"
    )

@app.get("/")
def root():
    return {"status": "OK"}
