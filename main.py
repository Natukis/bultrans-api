# main.py
import os
import uuid
from fastapi import FastAPI, UploadFile, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from process import process_invoice_upload
from suppliers_api import router as suppliers_router  # ← חדש

app = FastAPI(title="BulTrans API")

# --- CORS (מה-ENV, עם ברירת מחדל מתאימה ל-Base44 + localhost) ---
origins_env = os.getenv(
    "ALLOWED_ORIGINS",
    "https://preview--bul-trans-e5149297.base44.app,https://app--bul-trans-e5149297.base44.app,http://localhost:3000"
)
allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- request_id לכל בקשה ---
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

# --- errors uniform ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": "HTTP_ERROR",
            "message": str(exc.detail),
            "request_id": getattr(request.state, "request_id", None),
        },
    )

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    debug = os.getenv("DEBUG", "0") == "1"
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "message": "Unexpected error",
            "details": str(exc) if debug else None,
            "request_id": getattr(request.state, "request_id", None),
        },
    )

# --- Routers ---
app.include_router(suppliers_router)  # ← חדש

@app.get("/ping")
async def ping():
    return {"success": True, "message": "API is alive!"}

@app.post("/process-invoice/")
async def process_invoice(supplier_id: str = Form(...), file: UploadFile = Form(...)):
    return await process_invoice_upload(supplier_id, file)

@app.get("/")
def root():
    return {"message": "BulTrans API is ready"}
