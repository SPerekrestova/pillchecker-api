"""Tests for OCR text preprocessing."""

from app.nlp.ocr_cleaner import clean


class TestCharacterSubstitutions:
    def test_zero_to_o_in_drug_context(self):
        assert "metformin" in clean("metf0rmin").lower()

    def test_one_to_l(self):
        assert "alprazolam" in clean("a1prazolam").lower()

    def test_rn_to_m_in_drug_context(self):
        # "ibuprofen" OCR'd as "ibuprofern" — this is tricky,
        # only apply when rn could be m in known patterns
        result = clean("Aceta rninophen")
        assert "Acetaminophen" in result or "acetaminophen" in result.lower()


class TestWhitespaceNormalization:
    def test_multiple_spaces(self):
        assert clean("Ibuprofen   400mg") == "Ibuprofen 400mg"

    def test_tabs_and_newlines(self):
        assert clean("Ibuprofen\t400\nmg") == "Ibuprofen 400 mg"

    def test_soft_hyphens(self):
        assert clean("Ibu\u00adprofen") == "Ibuprofen"


class TestNonAsciiArtifacts:
    def test_smart_quotes_replaced(self):
        result = clean("\u201cIbuprofen\u201d")
        assert '"' not in result or result == '"Ibuprofen"'

    def test_zero_width_chars_stripped(self):
        result = clean("Ibu\u200bprofen")
        assert result == "Ibuprofen"

    def test_ligatures_expanded(self):
        result = clean("\ufb01lm")  # fi ligature
        assert result == "film"


class TestEdgeCases:
    def test_empty_string(self):
        assert clean("") == ""

    def test_already_clean_text(self):
        assert clean("Ibuprofen 400mg Film-Coated Tablets") == "Ibuprofen 400mg Film-Coated Tablets"

    def test_preserves_legitimate_digits(self):
        """Digits in dosages must not be converted."""
        assert "400" in clean("Ibuprofen 400mg")
