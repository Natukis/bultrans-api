from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from process import process_invoice_upload
import os

app = FastAPI()

# ✅ מתיר בקשות רק מהאתר שלך ב־Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app--bul-trans-e5149297.base44.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ עיבוד חשבונית
@app.post("/process-invoice/")
async def process_invoice(
    supplier_id: str = Form(...),
    file: UploadFile = Form(...),
    template: UploadFile = Form(...)
):
    return await process_invoice_upload(supplier_id, file, template)

# ✅ הורדת קובץ מוכן
@app.get("/download-invoice/{filename}")
def download_invoice(filename: str):
    file_path = f"/tmp/{filename}"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename)
    return JSONResponse({"error": "File not found"}, status_code=404)

# ✅ בדיקת חיבור לשרת (פינג)
@app.get("/process-invoice/")
def ping():
    return {"success": True, "message": "API is up and running"}
