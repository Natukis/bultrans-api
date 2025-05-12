from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from process import process_invoice_upload

app = FastAPI()

# ✅ פתרון שגיאת CORS – מאפשר גם preview וגם production של Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://preview--bul-trans-e5149297.base44.app",
        "https://app--bul-trans-e5149297.base44.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
async def ping():
    return {"success": True, "message": "API is alive!"}

@app.post("/process-invoice/")
async def process_invoice(supplier_id: str = Form(...), file: UploadFile = Form(...)):
    return await process_invoice_upload(supplier_id, file)

@app.get("/")
def root():
    return {"message": "BulTrans API is ready"}
