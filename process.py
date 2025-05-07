async def process_invoice_upload(client_id: int, file: UploadFile, template: UploadFile):
    try:
        invoice_path = os.path.join(UPLOAD_DIR, file.filename)
        template_path = os.path.join(UPLOAD_DIR, template.filename)

        # שמירת הקבצים
        with open(invoice_path, "wb") as f:
            f.write(await file.read())
        with open(template_path, "wb") as f:
            f.write(await template.read())

        # קריאת תוכן מהחשבונית (PDF או DOCX)
        text = ""
        if invoice_path.lower().endswith(".pdf"):
            reader = PdfReader(invoice_path)
            text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        elif invoice_path.lower().endswith(".docx"):
            from docx import Document
            doc = Document(invoice_path)
            text = "\n".join([para.text for para in doc.paragraphs])
        else:
            return JSONResponse(content={"success": False, "error": "Unsupported invoice file type"})

        # המשך טיפול רגיל
        clients = pd.read_excel(CLIENT_TABLE_PATH)
        client_row = clients[clients["Company ID"] == client_id]
        if client_row.empty:
            return JSONResponse(content={"success": False, "error": "Client not found"})

        invoice_number = str(int(client_row["Last invoice number"].values[0]) + 1).zfill(10)
        invoice_date = extract_field(r"Date:\s*([\d/\.]+)", text).replace("/", ".")

        match = re.search(r"Total Amount of Bill:\s*([A-Z]{3})\s*([\d\.,]+)", text)
        currency, amount = (match.group(1), float(match.group(2).replace(",", ""))) if match else ("EUR", 0)

        exchange_rate = get_exchange_rate(invoice_date, currency)
        amount_bgn = round(amount * exchange_rate, 2)

        data = {
            "InvoiceNumber": invoice_number,
            "Date": invoice_date,
            "CustomerName": extract_field(r"Customer Name:\s*(.+)", text),
            "SupplierName": extract_field(r"Supplier:\s*(.+)", text),
            "Amount": amount,
            "AmountBGN": amount_bgn,
            "ExchangeRate": exchange_rate,
            "Currency": currency,
            "IBAN": client_row["IBAN"].values[0],
            "BankName": client_row["Bank name"].values[0],
        }

        output_path = f"/tmp/bulgarian_invoice_{invoice_number}.docx"
        doc = DocxTemplate(template_path)
        doc.render(data)
        doc.save(output_path)

        return JSONResponse(content={
            "success": True,
            "invoice_number": invoice_number,
            "file_path": output_path
        })

    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})
