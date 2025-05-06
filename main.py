# main.py
from fastapi import FastAPI
from fastapi.responses import FileResponse
from process import process_invoice

app = FastAPI()

@app.post("/process-invoice")
def process_invoice_api(data: dict):
    return process_invoice(
        data["file_url"],
        data["template_path"],
        data["client_id"]
    )

@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = f"/tmp/{filename}"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
