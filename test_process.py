
import pytest
from process import (
    translate_text,
    extract_invoice_date,
    number_to_bulgarian_words,
    extract_customer_info,
    safe_extract_float
)

def test_translate_text():
    assert translate_text("Sofia") == "София"
    assert translate_text("Banana Express EOOD") == "Банана Експрес ЕООД"
    assert translate_text("QUESTE LTD") == "Куесте ООД"

def test_number_to_bulgarian_words():
    assert number_to_bulgarian_words(5640) == "пет хиляди шестстотин и четиридесет лева"
    assert number_to_bulgarian_words(700) == "седемстотин лева"
    assert number_to_bulgarian_words(999) == "999 лева"

def test_extract_invoice_date():
    text1 = "Invoice date: 18/08/2021"
    text2 = "Date issued: 2021-08-18"
    text3 = "Dated: August 18, 2021"
    text4 = "Dated: Aug 18, 2021"
    assert extract_invoice_date(text1)[0] == "18.08.2021"
    assert extract_invoice_date(text2)[0] == "18.08.2021"
    assert extract_invoice_date(text3)[0] == "18.08.2021"
    assert extract_invoice_date(text4)[0] == "18.08.2021"

def test_extract_customer_info_mixed_text():
    sample_text = (
        "Customer Name: QUESTE LTD Supplier\n"
        "ID No: 203743737\n"
        "VAT No: BG203743737\n"
        "Address: Aleksandar Stamboliiski 134\n"
        "City: Sofia\n"
        "Supplier: Banana Express EOOD\n"
        "VAT No: BG206232541\n"
        "ID: 206232541\n"
        "Address: Business Park Varna, Building 8"
    )
    result = extract_customer_info(sample_text)
    assert result["RecipientName"] == "Куесте ООД"
    assert result["RecipientID"] == "203743737"
    assert result["RecipientVAT"] == "BG203743737"
    assert "Александър Стамболийски" in result["RecipientAddress"]
    assert result["RecipientCity"] == "София"

def test_customer_name_cleaning():
    text = "Customer Name: QUESTE LTD Supplier"
    assert "Supplier" not in extract_customer_info(text)["RecipientName"]

def test_total_amount_extraction():
    example_text = (
        "Total Amount: BGN 4 700.00\n"
        "VAT Amount: BGN 940.00\n"
        "Total Amount of Bill: BGN 5 640.00"
    )
    lines = example_text.splitlines()
    values = [safe_extract_float(line) for line in lines]
    assert values == [4700.00, 940.00, 5640.00]
