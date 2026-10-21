import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import main

class JobDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(r"Z:\МОРЕ\ОБОБЩЕНКА_ОТПРАВКА")
        self.ice = Path(r"\\files.aari.ru\Ice_charts")
        self.website = Path(r"\\data.aari.ru\d0015\arctic")
    def test_wednesday_job_names_and_destinations(self):
        with patch.multiple(main, SOURCE_ROOT=self.source, ICE_CHARTS_ROOT=self.ice):
            jobs = main.build_jobs(date(2026, 10, 21), "wednesday")
        by_name = {j.name:j for j in jobs}
        self.assertEqual(by_name["Запад: SHP"].sources[0].name, "20261020З.shp")
        self.assertEqual(by_name["Восток: SHP"].sources[0].name, "20261020В.shp")
        self.assertEqual(by_name["Обобщенная: SIGRID3"].target_dir, self.ice / "Обобщенная" / "SIGRID3" / "2026" / "10")
    def test_oldshore_before_noon_uses_old_shore_source(self):
        with patch.multiple(main, SOURCE_ROOT=self.source, ICE_CHARTS_ROOT=self.ice):
            jobs = main.build_jobs(date(2026, 10, 21), "oldshore")
        self.assertEqual(jobs[0].sources[0], self.source / "2026-10-21" / "old_shore" / "20261020О.shp")
    def test_thursday_jobs_use_lvp_and_previous_week_website(self):
        with patch.multiple(main, SOURCE_ROOT=self.source, ICE_CHARTS_ROOT=self.ice, WEBSITE_ROOT=self.website):
            jobs = main.build_jobs(date(2026, 10, 22), "thursday")
        by_name = {j.name:j for j in jobs}
        self.assertEqual(by_name["LVP_WAVE"].sources[0], self.source / "2026-10-21" / "LVP" / "20261020.shp")
        self.assertEqual(by_name["Сайт: GIF RU"].sources[0], self.source / "2026-10-14" / "website" / "20261013.gif")
        self.assertEqual(by_name["Сайт: SIGRID + ZIP"].sources[-1].name, "aari_arc_20261013_pl_a.zip")
        self.assertEqual(by_name["Сайт: SIGRID + ZIP"].target_dir, self.website / "sigrid" / "2026")

if __name__ == "__main__":
    unittest.main()
