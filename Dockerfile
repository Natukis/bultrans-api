# ========= Base =========
FROM python:3.10-slim

# Prevent Python from writing .pyc files and ensure stdout/stderr are unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ========= System deps (OCR + PDF + fonts) =========
# - tesseract-ocr (+ Bulgarian & English language packs)
# - poppler-utils for pdf2image
# - libreoffice for DOCX -> PDF (headless)
# - fonts for Cyrillic rendering
# - X libs some libs python imaging stacks expect
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-bul \
      tesseract-ocr-eng \
      poppler-utils \
      libreoffice \
      fonts-dejavu \
      fontconfig \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 && \
    rm -rf /var/lib/apt/lists/*

# ========= Python deps =========
# Copy requirements first to leverage Docker layer cache
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# (Optional) Dev requirements – uncomment if you want them in the image
# COPY requirements-dev.txt .
# RUN pip install -r requirements-dev.txt

# ========= App code =========
COPY . .

# ========= (Optional) non-root user for better security =========
# If you prefer running as non-root; comment out if it breaks local perms
RUN addgroup --system app && adduser --system --ingroup app app && \
    chown -R app:app /app
USER app

# ========= Runtime =========
EXPOSE 8000
# Uvicorn server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
