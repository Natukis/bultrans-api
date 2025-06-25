import pytest
import re
from datetime import datetime
import os
import pandas as pd

# ייבוא הפונקציות מהקוד הראשי - עודכן סופית
from process import (
    auto_translate,
    number_to_bulgarian_words,
    extract_invoice_date,
    extract_recipient_details,
    extract_service_lines,
    get_template_path_by_rows
)

# עוזר קטן לבדוק אם יש אותיות קיריליות
def is_cyrillic(text):
    if not text:
        return False
    return bool(re.search(r'[А-Яа-я]', text))

# --- בדיקות ליבה ---

def test_auto_translate():
    if os.getenv("GOOGLE_API_KEY"):
        result = auto_translate("Sofia")
        assert isinstance(result, str)
        assert is_cyrillic(result)
    else:
        pytest.skip("Skipping translation test: GOOGLE_API_KEY not set")

def test_number_to_bulgarian_words():
    # Test the main functionality which now always returns words
    assert "пет хиляди" in number_to_bulgarian_words(5640)
    assert "четиристотин" in number_to_bulgarian_words(469.4)
    assert "седемстотин лева и 00 стотинки" in number_to_bulgarian_words(700)

def test_extract_invoice_date():
    # The function now returns only a datetime object or None
    date_obj = extract_invoice_date("Invoice date: 18/08/2021")
    assert isinstance(date_obj, datetime)
    assert date_obj.strftime("%d.%m.%Y") == "18.08.2021"
    
    date_obj_none = extract_invoice_date("Some random text without a date")
    assert date_obj_none is None

# --- THIS TEST IS REWRITTEN FOR THE NEW HYBRID FUNCTION ---
def test_extract_recipient_details():
    text = (
        "Supplier Company Name\n"
        "Some Address for supplier\n"
        "VAT: BG111111111\n\n"
        "Bill To: QUESTE LTD\n"
        "ID No: 203743737\n"
        "VAT: BG203743737\n"
        "Address: Aleksandar Stamboliiski 134\n"
    )
    # Create a mock supplier_data object, similar to what pandas reads from Excel
    supplier_data = pd.Series({
        "SupplierCompanyVAT": "BG111111111",
        "SupplierName": "Supplier Company Name"
    })

    # Call the new function with the correct arguments
    result = extract_recipient_details(text, supplier_data)
    
    assert result['name'] == "QUESTE LTD"
    assert result['vat'] == "BG203743737"
    assert result['id'] == "203743737"
    assert result['address'] == "Aleksandar Stamboliiski 134"

def test_extract_service_lines():
    text_with_table = """
    Some text before
    Description           Amount
    Service A - Consulting   1000.00
    Service B - Design       250.50
    Subtotal                 1250.50
    """
    result = extract_service_lines(text_with_table)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]['description'] == 'Service A - Consulting'
    assert result[0]['line_total'] == 1000.00

def test_get_template_path_by_rows():
    base_path = "templates"
    os.makedirs(base_path, exist_ok=True)
    for i in range(1, 6):
        with open(os.path.join(base_path, f"BulTrans_Template_{i}row.docx"), "w") as f:
            f.write("dummy")

    assert get_template_path_by_rows(1).endswith(os.path.join("templates", "BulTrans_Template_1row.docx"))
    assert get_template_path_by_rows(3).endswith(os.path.join("templates", "BulTrans_Template_3row.docx"))
    assert get_template_path_by_rows(5).endswith(os.path.join("templates", "BulTrans_Template_5row.docx"))
    assert get_template_path_by_rows(6).endswith(os.path.join("templates", "BulTrans_Template_5row.docx"))
    assert get_template_path_by_rows(0).endswith(os.path.join("templates", "BulTrans_Template_1row.docx"))
