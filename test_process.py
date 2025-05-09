import pytest
from process import number_to_bulgarian_words, safe_extract_float

def test_number_to_bulgarian_words():
    assert number_to_bulgarian_words(0) == "0 лева"
    assert number_to_bulgarian_words(1) == "едно лева"
    assert number_to_bulgarian_words(700) == "седемстотин лева"
    assert number_to_bulgarian_words(940) == "деветстотин и четиридесет лева"
    assert number_to_bulgarian_words(4700) == "четири хиляди и седемстотин лева"
    assert number_to_bulgarian_words(5640) == "пет хиляди шестстотин и четиридесет лева"

def test_safe_extract_float():
    assert safe_extract_float("1,200.50") == 1200.50
    assert safe_extract_float("3 400,00") == 3400.00
    assert safe_extract_float("BGN 9,999") == 9999.0
    assert safe_extract_float("USD 3,500.25") == 3500.25
    assert safe_extract_float("Total Amount: 4 700") == 4700.0
