import pytest
import re
from datetime import datetime

# Import the new, core functions from the refactored process.py
from process import (
    auto_translate,
    number_to_bulgarian_words,
    extract_invoice_date,
    clean_number,
    extract_customer_details,
    extract_service_lines
)

# Helper functions for testing
def is_cyrillic(text):
    if not text: return False
    return bool(re.search(r'[А-Яа-я]', text))

def not_latin_only(text):
    # This check is now more specific to "is it transliterated?"
    if not text: return False
    return any('\u0400' <= char <= '\u04FF' for char in text)

# --- Tests for Preserved Functions (No changes needed) ---

def test_auto_translate():
    result = auto_translate("Sofia")
    assert isinstance(result, str)
    assert is_cyrillic(result)

def test_number_to_bulgarian_words():
    assert number_to_bulgarian_words(5640, as_words=False) == "5640 лв."
    assert number_to_bulgarian_words(700, as_words=False) == "700 лв."
    assert "пет хиляди" in number_to_bulgarian_words(5640, as_words=True)
    assert "четиристотин" in number_to_bulgarian_words(469.4, as_words=True)

def test_extract_invoice_date():
    date_str, date_obj = extract_invoice_date("Invoice date: 18/08/2021")
    assert date_str == "18.08.2021"
    assert isinstance(date_obj, datetime)

# --- NEW / REWRITTEN TESTS for Refactored Code ---

def test_clean_number():
    """Tests the new number cleaning function."""
    assert clean_number("Total Amount: BGN 4,700.00") == 4700.0
    assert clean_number("VAT Amount: BGN 940.00") == 940.0
    assert clean_number("Total Amount of Bill: BGN 5.640,00") == 5640.0

def test_extract_customer_details():
    """Tests the new core customer detail extraction."""
    text = (
        "Customer Name: QUESTE LTD Supplier\n"
        "ID No: 203743737\n"
        "VAT No: BG203743737\n"
        "Address: Aleksandar Stamboliiski 134\n"
        "City: Sofia"
    )
    # Test the core extraction function
    result = extract_customer_details(text, supplier_name="Supplier")
    
    # Assert that the RAW, UNTRANSLATED data is extracted correctly
    assert result['name'] == "QUESTE LTD"
    assert result['vat'] == "BG203743737"
    assert result['id'] == "203743737"
    assert result['address'] == "Aleksandar Stamboliiski 134"
    
    # The new function translates the city, so we check if it's Cyrillic
    assert is_cyrillic(result['city'])

def test_extract_service_lines():
    """Tests the new multi-line service extraction."""
    text_with_table = """
    Some text before
    Description          Amount
    Service A - Consulting   1000.00
    Service B - Design       250.50
    Subtotal                 1250.50
    """
    result = extract_service_lines(text_with_table)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]['description'] == 'Service A - Consulting'
    assert result[0]['line_total'] == 1000.00
    assert result[1]['description'] == 'Service B - Design'
    assert result[1]['line_total'] == 250.50
    
    text_no_table = """
    Invoice for various consulting services based on our agreement.
    This invoice is to be paid within 30 days.
    Total Amount Due: 500.00
    """
    result_fallback = extract_service_lines(text_no_table)
    assert len(result_fallback) == 1
    assert result_fallback[0]['line_total'] == 500.00
    assert "Consulting services" in result_fallback[0]['description']
