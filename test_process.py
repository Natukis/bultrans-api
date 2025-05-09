import pytest
from process_ready_for_deploy import (
    translate_text,
    extract_invoice_date,
    number_to_bulgarian_words,
    extract_customer_info,
    safe_extract_float
)

def test_translate_text():
    assert translate_text("Sofia") == "София"
    assert translate_text("Aleksandar Stamboliiski") == "Александър Стамболийски"

def test_number_to_bulgarian_words():
    assert number_to_bulgarian_words(5640) == "пет хиляди шестстотин и четиридесет лева"
    assert number_to_bulgarian_words(700) == "седемстотин лева"
    assert number_to_bulgarian_words(1) == "едно лева"
    assert number_to_bulgarian_words(0) == "0 лева"

def test_extract_invoice_date():
    assert extract_invoice_date("Invoice date: 18/08/2021")[0] == "18.08.2021"
    assert extract_invoice_date("Date issued: 2021-08-18")[0] == "18.08.2021"
    assert extract_invoice_date("Dated: August 18, 2021")[0] == "18.08.2021"
    assert extract_invoice_date("Dated: Aug 18, 2021")[0] == "18.08.2021"

def test_extract_customer_info():
    text = (
        "Customer Name: QUESTE LTD Supplier\n"
        "ID No: 203743737\n"
        "VAT No: BG203743737\n"
        "Address: Aleksandar Stamboliiski 134\n"
        "City: Sofia"
    )
    result = extract_customer_info(text)
    assert result["RecipientName"] == "Куесте ООД"
    assert result["RecipientID"] == "203743737"
    assert result["RecipientVAT"] == "BG203743737"
    assert result["RecipientAddress"] == "Александър Стамболийски 134"
    assert result["RecipientCity"] == "София"

def test_safe_extract_float():
    assert safe_extract_float("Total Amount: BGN 4 700.00") == 4700.0
    assert safe_extract_float("VAT Amount: BGN 940.00") == 940.0
    assert safe_extract_float("Total Amount of Bill: BGN 5 640.00") == 5640.0
