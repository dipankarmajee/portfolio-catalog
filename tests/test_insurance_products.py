"""
Unit tests for IRDAI Insurance Products Scraper and Insurance Collector modules.

Tests cover:
  1. UIN regex validation (_parse_uin)
  2. Category classification (_classify_category)
  3. Date parsing (_parse_date)
  4. Schema initialization (init_insurance_schema)
  5. Searchable name builder (_build_searchable_name)
  6. Database upsert logic (_upsert_batch)
  7. Mock-based scraper test (scrape_all_products)
"""

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Lazy imports — the modules may not exist yet while the implementation
# subagent is still running.  Each test class imports what it needs inside
# setUp so the rest of the suite can still be collected.
# ---------------------------------------------------------------------------


# ===========================================================================
# 1. UIN Regex Validation
# ===========================================================================


class TestParseUIN(unittest.TestCase):
    """Tests for IRDAIProductsScraper._parse_uin()"""

    def setUp(self):
        from modules.insurance.irdai_products_scraper import IRDAIProductsScraper
        self.parse_uin = IRDAIProductsScraper._parse_uin

    # --- Valid UINs (bare) ---------------------------------------------------

    def test_valid_uin_life_N(self):
        self.assertEqual(self.parse_uin("111N1333V03"), "111N1333V03")

    def test_valid_uin_life_L(self):
        self.assertEqual(self.parse_uin("101L063V05"), "101L063V05")

    def test_valid_uin_L_leading_zeros(self):
        self.assertEqual(self.parse_uin("512L001V01"), "512L001V01")

    def test_valid_uin_N_short_number(self):
        self.assertEqual(self.parse_uin("135N009V02"), "135N009V02")

    # --- UIN embedded inside longer text ------------------------------------

    def test_uin_embedded_in_text(self):
        text = "SBI Life - Smart Platina Plus UIN: 111N1333V03"
        self.assertEqual(self.parse_uin(text), "111N1333V03")

    def test_uin_embedded_mid_sentence(self):
        text = "Product 101L063V05 is an active plan."
        self.assertEqual(self.parse_uin(text), "101L063V05")

    # --- Multiple UINs — should return the FIRST match ----------------------

    def test_multiple_uins_returns_first(self):
        text = "111N1333V03 and 101L063V05 are both valid."
        self.assertEqual(self.parse_uin(text), "111N1333V03")

    # --- Invalid UINs --------------------------------------------------------

    def test_invalid_uin_too_short_digits_before(self):
        # Only 2 digits before N (needs 3)
        self.assertIsNone(self.parse_uin("11N1333V03"))

    def test_invalid_uin_too_short_middle(self):
        # Only 2 digits in middle section (needs at least 3 digits)
        self.assertIsNone(self.parse_uin("111N13V03"))

    def test_invalid_uin_letters_instead_of_digits(self):
        # Leading part has letters
        self.assertIsNone(self.parse_uin("ABCN1333V03"))

    def test_invalid_uin_empty_string(self):
        self.assertIsNone(self.parse_uin(""))

    def test_invalid_uin_random_text(self):
        self.assertIsNone(self.parse_uin("No UIN here at all"))

    # --- Edge cases ----------------------------------------------------------

    def test_none_input_returns_none(self):
        """Should not raise; should return None when given None."""
        self.assertIsNone(self.parse_uin(None))

    def test_whitespace_only_returns_none(self):
        self.assertIsNone(self.parse_uin("   "))


# ===========================================================================
# 2. Category Classification
# ===========================================================================


class TestClassifyCategory(unittest.TestCase):
    """Tests for IRDAIProductsScraper._classify_category()"""

    def setUp(self):
        from modules.insurance.irdai_products_scraper import IRDAIProductsScraper
        self.classify = IRDAIProductsScraper._classify_category

    def test_ulip_plain(self):
        self.assertEqual(self.classify("Unit Linked Insurance Plan"), "ULIP")

    def test_ulip_takes_priority_over_endowment(self):
        """'linked' keyword beats 'endowment'."""
        self.assertEqual(self.classify("Linked Endowment Plan"), "ULIP")

    def test_term_assurance(self):
        self.assertEqual(self.classify("Term Assurance Plan"), "Term Assurance")

    def test_endowment_via_guaranteed(self):
        self.assertEqual(
            self.classify("Smart Platina Plus - Guaranteed Savings Plan"),
            "Endowment",
        )

    def test_endowment_via_endowment_keyword(self):
        self.assertEqual(self.classify("New Endowment Plan"), "Endowment")

    def test_endowment_via_savings_keyword(self):
        self.assertEqual(self.classify("Savings Plus Plan"), "Endowment")

    def test_whole_life(self):
        self.assertEqual(self.classify("Jeevan Umang Whole Life Plan"), "Whole Life")

    def test_annuity_via_annuity(self):
        self.assertEqual(self.classify("Smart Annuity Plus"), "Annuity")

    def test_annuity_via_pension(self):
        self.assertEqual(self.classify("Pension Plus Plan"), "Annuity")

    def test_health(self):
        self.assertEqual(self.classify("Health Companion"), "Health")

    def test_rider(self):
        self.assertEqual(self.classify("Accidental Death Rider"), "Rider")

    def test_group(self):
        self.assertEqual(self.classify("Group Term Insurance"), "Group")

    def test_other_no_keywords(self):
        self.assertEqual(self.classify("Smart Shield"), "Other")

    def test_case_insensitivity(self):
        """Classification should be case-insensitive."""
        self.assertEqual(self.classify("TERM ASSURANCE PLAN"), "Term Assurance")
        self.assertEqual(self.classify("unit linked plan"), "ULIP")

    def test_empty_string_returns_other(self):
        self.assertEqual(self.classify(""), "Other")


# ===========================================================================
# 3. Date Parsing
# ===========================================================================


class TestParseDate(unittest.TestCase):
    """Tests for IRDAIProductsScraper._parse_date()"""

    def setUp(self):
        from modules.insurance.irdai_products_scraper import IRDAIProductsScraper
        self.parse_date = IRDAIProductsScraper._parse_date

    def test_dd_mm_yyyy_slash(self):
        self.assertEqual(self.parse_date("15/03/2020"), "2020-03-15")

    def test_dd_mon_yyyy(self):
        self.assertEqual(self.parse_date("15-Mar-2020"), "2020-03-15")

    def test_iso_format(self):
        self.assertEqual(self.parse_date("2020-03-15"), "2020-03-15")

    def test_long_month_name(self):
        self.assertEqual(self.parse_date("March 15, 2020"), "2020-03-15")

    def test_empty_string_returns_none(self):
        self.assertIsNone(self.parse_date(""))

    def test_na_uppercase_returns_none(self):
        self.assertIsNone(self.parse_date("N/A"))

    def test_na_lowercase_returns_none(self):
        self.assertIsNone(self.parse_date("na"))

    def test_none_input_returns_none(self):
        self.assertIsNone(self.parse_date(None))

    def test_invalid_string_returns_none(self):
        self.assertIsNone(self.parse_date("invalid date string"))

    def test_whitespace_returns_none(self):
        self.assertIsNone(self.parse_date("   "))


# ===========================================================================
# 4. Schema Initialization
# ===========================================================================


class TestInitInsuranceSchema(unittest.TestCase):
    """Tests for insurance_collector.init_insurance_schema()"""

    def setUp(self):
        from modules.insurance.insurance_collector import init_insurance_schema
        self.init_schema = init_insurance_schema
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def _get_table_names(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        return {row[0] for row in cur.fetchall()}

    def _get_index_names(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        return {row[0] for row in cur.fetchall()}

    def _get_column_names(self, table):
        cur = self.conn.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}

    def test_creates_master_insurance_products_table(self):
        self.init_schema(self.conn)
        self.assertIn("master_insurance_products", self._get_table_names())

    def test_table_has_expected_columns(self):
        self.init_schema(self.conn)
        cols = self._get_column_names("master_insurance_products")
        for expected in [
            "uin",
            "product_name",
            "name",
            "insurer_name",
            "category",
            "status",
            "launch_date",
            "updated_at",
        ]:
            self.assertIn(expected, cols, f"Column '{expected}' is missing")

    def test_creates_insurer_index(self):
        self.init_schema(self.conn)
        self.assertIn("idx_ins_prod_insurer", self._get_index_names())

    def test_creates_category_index(self):
        self.init_schema(self.conn)
        self.assertIn("idx_ins_prod_category", self._get_index_names())

    def test_creates_status_index(self):
        self.init_schema(self.conn)
        self.assertIn("idx_ins_prod_status", self._get_index_names())

    def test_creates_schema_documentation_table(self):
        self.init_schema(self.conn)
        self.assertIn("_schema_documentation", self._get_table_names())

    def test_idempotent_schema_creation(self):
        """Calling init twice should not raise an error."""
        self.init_schema(self.conn)
        self.init_schema(self.conn)
        self.assertIn("master_insurance_products", self._get_table_names())


# ===========================================================================
# 5. Searchable Name Builder
# ===========================================================================


class TestBuildSearchableName(unittest.TestCase):
    """Tests for insurance_collector._build_searchable_name()"""

    def setUp(self):
        from modules.insurance.insurance_collector import _build_searchable_name
        self.build = _build_searchable_name

    def test_sbi_life(self):
        self.assertEqual(
            self.build("SBI Life Insurance Company Limited", "Smart Platina Plus"),
            "SBI Life - Smart Platina Plus",
        )

    def test_lic(self):
        self.assertEqual(
            self.build("Life Insurance Corporation of India", "New Jeevan Anand"),
            "LIC - New Jeevan Anand",
        )

    def test_hdfc_life(self):
        self.assertEqual(
            self.build("HDFC Life Insurance Co. Ltd.", "Click 2 Protect"),
            "HDFC Life - Click 2 Protect",
        )

    def test_empty_insurer(self):
        """When insurer is empty, return only product name."""
        self.assertEqual(self.build("", "Smart Shield"), "Smart Shield")

    def test_no_duplication_when_product_starts_with_brand(self):
        """
        If the product name already starts with the short brand, do not
        create a 'BrandName - BrandName Product' duplicate.
        """
        result = self.build(
            "Bajaj Allianz Life Insurance Limited",
            "Bajaj Allianz Smart Wealth Goal",
        )
        self.assertEqual(result, "Bajaj Allianz Smart Wealth Goal")

    def test_insurer_none_treated_as_empty(self):
        """None insurer should not raise; just return product name."""
        result = self.build(None, "Some Product")
        self.assertIn("Some Product", result)


# ===========================================================================
# 6. Database Upsert Test
# ===========================================================================


class TestUpsertBatch(unittest.TestCase):
    """Tests for the internal _upsert_batch helper via in-memory SQLite."""

    def setUp(self):
        from modules.insurance.insurance_collector import (
            init_insurance_schema,
            _upsert_batch,
        )
        self.upsert = _upsert_batch
        self.conn = sqlite3.connect(":memory:")
        init_insurance_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def _make_record(self, uin, product_name, insurer="Test Insurer", launch_date="2020-01-01"):
        return {
            "uin": uin,
            "product_name": product_name,
            "name": f"{insurer} - {product_name}",
            "insurer_name": insurer,
            "category": "Term Assurance",
            "status": "Active",
            "launch_date": launch_date,
        }

    def test_insert_two_records(self):
        batch = [
            self._make_record("111N1333V03", "Smart Platina Plus"),
            self._make_record("101L063V05", "Click 2 Protect", insurer="HDFC Life"),
        ]
        self.upsert(self.conn, batch)
        cur = self.conn.execute("SELECT COUNT(*) FROM master_insurance_products")
        self.assertEqual(cur.fetchone()[0], 2)

    def test_upsert_updates_product_name(self):
        """Re-inserting same UIN with different product_name should update it."""
        original = self._make_record("111N1333V03", "Smart Platina Plus")
        self.upsert(self.conn, [original])

        updated = self._make_record("111N1333V03", "Smart Platina Plus v2")
        self.upsert(self.conn, [updated])

        cur = self.conn.execute(
            "SELECT product_name FROM master_insurance_products WHERE uin=?",
            ("111N1333V03",),
        )
        self.assertEqual(cur.fetchone()[0], "Smart Platina Plus v2")

    def test_upsert_preserves_launch_date_via_coalesce(self):
        """
        On upsert, launch_date should be preserved (COALESCE keeps existing
        non-NULL value when new value is NULL).
        """
        original = self._make_record(
            "111N1333V03", "Smart Platina Plus", launch_date="2020-01-01"
        )
        self.upsert(self.conn, [original])

        # Second upsert without a launch_date
        no_date = self._make_record("111N1333V03", "Smart Platina Plus v2", launch_date=None)
        self.upsert(self.conn, [no_date])

        cur = self.conn.execute(
            "SELECT launch_date FROM master_insurance_products WHERE uin=?",
            ("111N1333V03",),
        )
        self.assertEqual(cur.fetchone()[0], "2020-01-01")

    def test_empty_batch_does_not_raise(self):
        self.upsert(self.conn, [])
        cur = self.conn.execute("SELECT COUNT(*) FROM master_insurance_products")
        self.assertEqual(cur.fetchone()[0], 0)


# ===========================================================================
# 7. Mock-based Scraper Test
# ===========================================================================

MOCK_HTML = """
<table>
  <tr>
    <th>Sr No</th><th>Insurer Name</th><th>Product Name</th>
    <th>UIN</th><th>Launch Date</th><th>Status</th>
  </tr>
  <tr>
    <td>1</td>
    <td>SBI Life Insurance Co. Ltd.</td>
    <td>Smart Platina Plus</td>
    <td>111N1333V03</td>
    <td>15/03/2020</td>
    <td>Active</td>
  </tr>
  <tr>
    <td>2</td>
    <td>HDFC Life Insurance Co. Ltd.</td>
    <td>Click 2 Protect Life</td>
    <td>101L063V05</td>
    <td>01/01/2019</td>
    <td>Active</td>
  </tr>
</table>
"""

EMPTY_HTML = "<table><tr><th>UIN</th></tr></table>"


class TestScrapeAllProductsMocked(unittest.TestCase):
    """
    Tests for IRDAIProductsScraper.scrape_all_products() with _fetch_page mocked out.
    Avoids needing to intercept the resilient session internals; instead we patch
    _fetch_page directly on the scraper instance.
    """

    def setUp(self):
        from modules.insurance.irdai_products_scraper import IRDAIProductsScraper
        self.ScraperClass = IRDAIProductsScraper

    def _get_products(self, html: str):
        """Helper: creates a scraper with _fetch_page returning mock soup, then None."""
        from bs4 import BeautifulSoup
        mock_soup = BeautifulSoup(html, "html.parser") if html else None

        scraper = self.ScraperClass()
        # _fetch_page returns mock_soup on first call, None afterwards (stops pagination)
        call_count = {"n": 0}

        def fake_fetch_page(url, timeout=30):
            call_count["n"] += 1
            return mock_soup if call_count["n"] == 1 else None

        scraper._fetch_page = fake_fetch_page
        return list(scraper.scrape_all_products())

    def test_scrape_yields_two_products(self):
        products = self._get_products(MOCK_HTML)
        self.assertEqual(len(products), 2)

    def test_scrape_first_product_uin(self):
        products = self._get_products(MOCK_HTML)
        uins = [p["uin"] for p in products]
        self.assertIn("111N1333V03", uins)

    def test_scrape_second_product_uin(self):
        products = self._get_products(MOCK_HTML)
        uins = [p["uin"] for p in products]
        self.assertIn("101L063V05", uins)

    def test_scrape_product_names(self):
        products = self._get_products(MOCK_HTML)
        names = [p["product_name"] for p in products]
        self.assertIn("Smart Platina Plus", names)
        self.assertIn("Click 2 Protect Life", names)

    def test_scrape_insurer_names(self):
        products = self._get_products(MOCK_HTML)
        insurers = [p["insurer_name"] for p in products]
        self.assertTrue(any("SBI" in i for i in insurers), "Expected SBI insurer in results")
        self.assertTrue(any("HDFC" in i for i in insurers), "Expected HDFC insurer in results")

    def test_scrape_empty_table_yields_nothing(self):
        """When the page has no UIN rows, the generator should be empty."""
        products = self._get_products(EMPTY_HTML)
        self.assertEqual(products, [])


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
