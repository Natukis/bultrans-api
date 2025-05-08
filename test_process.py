
import pytest
from datetime import datetime
from process import translate_text, extract_invoice_date, number_to_bulgarian_words

def test_translate_text():
    assert translate_text("Sofia") == "София"
    assert translate_text("Banana Express EOOD") == "Банана Експрес ЕООД"
    assert translate_text("QUESTE LTD") == "Куесте ООД"

def test_number_to_bulgarian_words():
    assert number_to_bulgarian_words(5640) == "пет хиляди шестстотин и четиридесет лева"
    assert number_to_bulgarian_words(700) == "седемстотин лева"
    assert number_to_bulgarian_words(999) == "999 лева"

def test_extract_invoice_date():
    # Standard formats
    text1 = "Invoice date: 18/08/2021"
    text2 = "Date issued: 2021-08-18"
    text3 = "Dated: August 18, 2021"
    text4 = "Dated: Aug 18, 2021"
    assert extract_invoice_date(text1)[0] == "18.08.2021"
    assert extract_invoice_date(text2)[0] == "18.08.2021"
    assert extract_invoice_date(text3)[0] == "18.08.2021"
    assert extract_invoice_date(text4)[0] == "18.08.2021"

def test_translate_edge_cases():
    text = "Address: Aleksandar Stamboliiski, Sofia"
    translated = translate_text(text)
    assert "Александър Стамболийски" in translated
    assert "София" in translated
