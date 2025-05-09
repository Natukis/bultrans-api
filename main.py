from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from process import process_invoice_upload
import os

app = FastAPI()

@app.post("/process-invoice/")
async def process_invoice(
    supplier_id: str = Form(...),
    file: UploadFile = Form(...),
    template: UploadFile = Form(...)
):
    return await process_invoice_upload(supplier_id, file, template)

@app.get("/download-invoice/{filename}")
def download_invoice(filename: str):
    file_path = f"/tmp/{filename}"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename)
    return JSONResponse({"error": "File not found"}, status_code=404)
