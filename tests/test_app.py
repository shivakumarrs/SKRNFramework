import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class MeterRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "meters.sqlite3"
        self.environment = patch.dict(
            os.environ,
            {"DATABASE_PATH": str(self.database_path)},
        )
        self.environment.start()
        from app import create_app

        self.client = create_app().test_client()

    def tearDown(self):
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_add_meter_page_and_registration_api(self):
        page = self.client.get("/meters/add")
        response = self.client.post(
            "/api/meters",
            json={
                "meter_id": "meter-new",
                "display_name": "New meter",
                "location": "North wing",
            },
        )
        meters = self.client.get("/api/meters").get_json()

        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Meter details", page.data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["meter"]["display_name"], "New meter")
        self.assertEqual(meters["meter_count"], 1)
        self.assertEqual(meters["meters"][0]["location"], "North wing")
        self.assertIsNone(meters["meters"][0]["latest_reading"])

    def test_registration_reports_invalid_and_duplicate_meter_ids(self):
        invalid = self.client.post("/api/meters", json={"meter_id": " "})
        self.client.post("/api/meters", json={"meter_id": "meter-duplicate"})
        duplicate = self.client.post(
            "/api/meters", json={"meter_id": "meter-duplicate"}
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__":
    unittest.main()
