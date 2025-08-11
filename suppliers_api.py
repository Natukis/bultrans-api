# suppliers_api.py
import os, io, json, time
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
import pandas as pd

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])

SUPPLIERS_DIR = os.getenv("SUPPLIERS_DIR", "/app/data/suppliers")
POINTER_FILE = os.path.join(SUPPLIERS_DIR, "current.json")
os.makedirs(SUPPLIERS_DIR, exist_ok=True)

def _list_versions() -> list[dict]:
    items = []
    for name in os.listdir(SUPPLIERS_DIR):
        if name.endswith(".xlsx"):
            path = os.path.join(SUPPLIERS_DIR, name)
            items.append({
                "version": name,
                "path": path,
                "mtime": os.path.getmtime(path)
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items

def _get_current_path(default_fallback: Optional[str] = None) -> str:
    if os.path.exists(POINTER_FILE):
        try:
            with open(POINTER_FILE, "r", encoding="utf-8") as f:
                p = json.load(f).get("current")
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass
    if default_fallback and os.path.exists(default_fallback):
        return default_fallback
    # אם אין כלום עדיין — ניצור קובץ ריק מינימלי
    empty = os.path.join(SUPPLIERS_DIR, "suppliers_empty.xlsx")
    if not os.path.exists(empty):
        pd.DataFrame(columns=["SupplierCompanyID"]).to_excel(empty, index=False)
    return empty

def _set_current_path(path: str) -> None:
    with open(POINTER_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": path}, f, ensure_ascii=False, indent=2)

@router.post("/upload")
async def upload_suppliers(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload an .xlsx file")
    version = time.strftime("%Y%m%d-%H%M%S") + "_" + file.filename.replace(" ", "_")
    dst = os.path.join(SUPPLIERS_DIR, version)
    data = await file.read()
    with open(dst, "wb") as f:
        f.write(data)
    # מעדכנים מצביע לגרסה הנוכחית
    _set_current_path(dst)
    # קוראים שורה-שתיים כדי להחזיר Preview בסיסי
    try:
        df = pd.read_excel(dst)
        preview = df.head(10).to_dict(orient="records")
        columns = list(df.columns)
        rows = len(df)
    except Exception as e:
        raise HTTPException(422, f"Uploaded file is not a valid Excel: {e}")
    return {
        "success": True,
        "version": os.path.basename(dst),
        "rows": rows,
        "columns": columns,
        "preview": preview
    }

@router.get("/preview")
def preview(limit: int = Query(50, ge=1, le=200), version: Optional[str] = None):
    path = _get_current_path() if not version else os.path.join(SUPPLIERS_DIR, version)
    if not os.path.exists(path):
        raise HTTPException(404, "Version not found")
    df = pd.read_excel(path)
    return {
        "success": True,
        "version": os.path.basename(path),
        "columns": list(df.columns),
        "rows": len(df),
        "data": df.head(limit).to_dict(orient="records"),
    }

@router.get("/versions")
def versions():
    lst = _list_versions()
    current = _get_current_path()
    return {
        "success": True,
        "current": os.path.basename(current) if current else None,
        "versions": [{"version": os.path.basename(x["path"]), "mtime": x["mtime"]} for x in lst]
    }

@router.post("/set-current")
def set_current(version: str):
    path = os.path.join(SUPPLIERS_DIR, version)
    if not os.path.exists(path):
        raise HTTPException(404, "Version not found")
    _set_current_path(path)
    return {"success": True, "current": version}

@router.get("/download")
def download(version: Optional[str] = None):
    path = _get_current_path() if not version else os.path.join(SUPPLIERS_DIR, version)
    if not os.path.exists(path):
        raise HTTPException(404, "Version not found")
    return FileResponse(path, filename=os.path.basename(path), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
