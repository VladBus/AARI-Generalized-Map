import unittest
from datetime import date
from main import png_name, product_date, release_range, russian_date_range


class DateRuleTests(unittest.TestCase):
    def test_wednesday_folder_uses_tuesday_chart_date(self):
        self.assertEqual(product_date(date(2026, 10, 21)), date(2026, 10, 20))

    def test_date_phrase(self):
        self.assertEqual(
            russian_date_range(date(2026, 10, 20)), "18-20 октября 2026 года"
        )

    def test_release_period_is_sunday_to_tuesday(self):
        self.assertEqual(
            release_range(date(2026, 10, 20)), (date(2026, 10, 18), date(2026, 10, 20))
        )

    def test_region_png_names(self):
        self.assertEqual(
            png_name(date(2026, 10, 20), "Восток"), "2026_10_18-20_Восток.png"
        )


if __name__ == "__main__":
    unittest.main()
