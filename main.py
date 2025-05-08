from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from process import process_invoice_upload

app = FastAPI()

# אפשר להתאים דומיין/מקור מאובטח
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # עדיף להגביל למקור מסוים בפרודקשן
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/process-invoice")
async def process_invoice(
    client_id: int = Form(...),
    file: UploadFile = Form(...),
    template: UploadFile = Form(...)
):
    return await process_invoice_upload(client_id, file, template)
