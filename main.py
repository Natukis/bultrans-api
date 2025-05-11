from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from process import process_invoice_upload, get_drive_service
import os

app = FastAPI()

# מתיר בקשות רק מהאתר שלך ב־Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app--bul-trans-e5149297.base44.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# עיבוד חשבונית
@app.post("/process-invoice/")
async def process_invoice(
    supplier_id: str = Form(...),
    file: UploadFile = Form(...)
):
    return await process_invoice_upload(supplier_id, file)

# הורדת קובץ מוכן
@app.get("/download-invoice/{filename}")
def download_invoice(filename: str):
    file_path = f"/tmp/{filename}"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename)
    return JSONResponse({"error": "File not found"}, status_code=404)

# בדיקת חיבור לשרת
@app.get("/ping")
def ping():
    return {"success": True, "message": "API is up and running"}

# בדיקת חיבור ל-Google Drive
@app.get("/test-drive")
def test_drive():
    try:
        service = get_drive_service()
        files = service.files().list(pageSize=1).execute()
        return {"success": True, "message": "Google Drive connection successful"}
    except Exception as e:
        return {"success": False, "error": str(e)}
