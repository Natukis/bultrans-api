import pytest
from process import (
    auto_translate,
    extract_invoice_date,
    number_to_bulgarian_words,
    extract_customer_info,
    safe_extract_float
)

def test_auto_translate():
    result = auto_translate("Sofia")
    assert isinstance(result, str)
    assert result != ""

def test_number_to_bulgarian_words():
    assert number_to_bulgarian_words(5640) == "5640 лв."
    assert number_to_bulgarian_words(700) == "700 лв."
    assert number_to_bulgarian_words(1) == "1 лв."
    assert number_to_bulgarian_words(0) == "0 лв."
    assert number_to_bulgarian_words(469.4) == "469 лв. и 40 ст."

def test_extract_invoice_date():
    assert extract_invoice_date("Invoice date: 18/08/2021")[0] == "18.08.2021"
    assert extract_invoice_date("Date issued: 2021-08-18")[0] == "18.08.2021"
    assert extract_invoice_date("Dated: August 18, 2021")[0] == "18.08.2021"
    assert extract_invoice_date("Dated: Aug 18, 2021")[0] == "18.08.2021"

def test_extract_customer_info_basic():
    text = (
        "Customer Name: QUESTE LTD Supplier\n"
        "ID No: 203743737\n"
        "VAT No: BG203743737\n"
        "Address: Aleksandar Stamboliiski 134\n"
        "City: Sofia"
    )
    result = extract_customer_info(text, supplier_name="Banana Express")
    assert result["RecipientName"].lower() == "queste ltd"
    assert result["RecipientID"] == "203743737"
    assert result["RecipientVAT"] == "BG203743737"
    assert "stamboliiski" in result["RecipientAddress"].lower()
    assert result["RecipientCity"].lower() == "sofia"

def test_extract_customer_info_mixed_line():
    text = (
        "Customer Name: ABC Ltd Supplier Company\n"
        "ID No: 111222333\n"
        "VAT No: BG111222333\n"
        "Address: Random Street 12\n"
        "City: Plovdiv"
    )
    result = extract_customer_info(text, supplier_name="Supplier Company")
    assert result["RecipientName"].lower() == "abc ltd"

def test_extract_customer_info_address_translation():
    text = (
        "Customer Name: Delta Inc\n"
        "ID No: 999888777\n"
        "VAT No: BG999888777\n"
        "Address: 5 Main Street\n"
        "City: Varna"
    )
    result = extract_customer_info(text, supplier_name="Something")
    assert "main" not in result["RecipientAddress"].lower()  # נבדק שתורגם

def test_safe_extract_float():
    assert safe_extract_float("Total Amount: BGN 4 700.00") == 4700.0
    assert safe_extract_float("VAT Amount: BGN 940.00") == 940.0
    assert safe_extract_float("Total Amount of Bill: BGN 5 640.00") == 5640.0
