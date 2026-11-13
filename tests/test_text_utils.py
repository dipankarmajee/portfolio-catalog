"""
tests/test_text_utils.py
Tests for text sanitization, Devanagari stripping, and identifier canonicalization.
"""

import unittest
from core.text_utils import (
    canonicalize_identifier,
    clean_corporate_tokens,
    clean_english_text,
    has_devanagari,
)


class TestTextUtils(unittest.TestCase):
    def test_clean_english_text_strips_devanagari(self):
        mixed = "भारतीय जीवन बीमा निगम / Life Insurance Corporation of India"
        cleaned = clean_english_text(mixed)
        self.assertEqual(cleaned, "Life Insurance Corporation of India")

    def test_clean_english_text_removes_punctuation_artifacts(self):
        sample = "  - / Axis Bluechip Fund - Direct Plan  "
        cleaned = clean_english_text(sample)
        self.assertEqual(cleaned, "Axis Bluechip Fund - Direct Plan")

    def test_strip_punctuation_prefix_and_trailing(self):
        from core.text_utils import strip_punctuation_prefix, strip_trailing_punctuation
        self.assertEqual(strip_punctuation_prefix("./ Kotak Ace"), "Kotak Ace")
        self.assertEqual(strip_punctuation_prefix(".\\ Star Union"), "Star Union")
        self.assertEqual(strip_punctuation_prefix("/ HDFC"), "HDFC")
        self.assertEqual(strip_trailing_punctuation("Kotak Mahindra Life Insurance Company."), "Kotak Mahindra Life Insurance Company")

    def test_clean_company_name_and_canonical_insurance_name(self):
        from core.text_utils import clean_company_name, build_canonical_insurance_name
        self.assertEqual(
            clean_company_name(". / Kotak Mahindra Life Insurance Company Ltd."),
            "Kotak Mahindra Life Insurance Co. Ltd."
        )
        self.assertEqual(
            clean_company_name("Kotak Mahindra Life Insurance Company."),
            "Kotak Mahindra Life Insurance Co. Ltd."
        )
        self.assertEqual(
            clean_company_name("Go Digit Life Insurance Limited."),
            "Go Digit Life Insurance Limited"
        )
        self.assertEqual(
            build_canonical_insurance_name(
                ". / Kotak Mahindra Life Insurance Company Ltd.",
                "Kotak Ace Investment"
            ),
            "Kotak Mahindra Life - Kotak Ace Investment"
        )
        self.assertEqual(
            build_canonical_insurance_name(
                ". / Star Union Dai-ichi Life Insurance Co Ltd.",
                "SUD Life Group Term Insurance Scheme"
            ),
            "Star Union Dai-ichi Life - SUD Life Group Term Insurance Scheme"
        )

    def test_has_devanagari(self):
        self.assertTrue(has_devanagari("एचडीएफसी बैंक"))
        self.assertFalse(has_devanagari("HDFC Bank Limited"))

    def test_canonicalize_identifier(self):
        self.assertEqual(canonicalize_identifier("STOCK", "TCS"), "STOCK_TCS")
        self.assertEqual(canonicalize_identifier("US_STOCK", "AAPL"), "US_STOCK_AAPL")
        self.assertEqual(canonicalize_identifier("MF", "120503"), "MF_120503")

    def test_clean_corporate_tokens(self):
        raw1 = "Life Insurance Corporation of India (LIC)"
        self.assertEqual(clean_corporate_tokens(raw1), "lic")

        raw2 = "HDFC Life Insurance Company Limited"
        self.assertEqual(clean_corporate_tokens(raw2), "hdfc")


if __name__ == "__main__":
    unittest.main()

