
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from process_final_debug import process_invoice_upload
import os

app = FastAPI()

@app.post("/process-invoice/")
async def generate_invoice(
    supplier_id: int = Form(...),
    file: UploadFile = File(...),
    template: UploadFile = File(...)
):
    return await process_invoice_upload(supplier_id, file, template)

@app.get("/download-invoice/{filename}")
def download_invoice(filename: str):
    file_path = f"/tmp/{filename}"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return JSONResponse(content={"error": "File not found"}, status_code=404)
