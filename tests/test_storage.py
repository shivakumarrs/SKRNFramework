from contextlib import closing
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from seed_demo_data import seed_demo_data
from storage import (
    initialize_database,
    list_meters,
    normalize_reading,
    register_meter,
    save_reading,
    summarize_readings,
)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "readings.sqlite3"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normalize_reading_converts_timestamp_to_utc(self):
        reading = normalize_reading(
            {
                "meter_id": "meter-1",
                "timestamp": "2026-01-02T03:00:00+03:00",
                "measurements": {"voltage_v": 230},
            }
        )
        self.assertEqual(reading["recorded_at"], "2026-01-02T00:00:00.000000Z")

    def test_normalize_reading_rejects_non_finite_measurement(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            normalize_reading(
                {"meter_id": "meter-1", "measurements": {"voltage_v": float("nan")}}
            )

    def test_save_reading_and_summarize(self):
        timestamp = datetime.now(timezone.utc).isoformat()
        save_reading(
            self.database_path,
            {
                "meter_id": "meter-1",
                "timestamp": timestamp,
                "measurements": {"voltage_v": 230, "current_a": 5},
            },
        )
        summary = summarize_readings(self.database_path)
        self.assertEqual(summary["reading_count"], 1)
        self.assertEqual(summary["meter_count"], 1)
        metrics = {metric["name"]: metric for metric in summary["metrics"]}
        self.assertEqual(metrics["voltage_v"]["average"], 230)
        self.assertEqual(metrics["current_a"]["latest"], 5)

    def test_demo_data_is_seeded_once(self):
        now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
        inserted = seed_demo_data(self.database_path, now)
        summary = summarize_readings(self.database_path)

        self.assertEqual(inserted, 338)
        self.assertEqual(summary["reading_count"], 338)
        self.assertEqual(summary["meter_count"], 2)
        self.assertEqual(
            {metric["name"] for metric in summary["metrics"]},
            {"voltage_v", "current_a", "active_power_kw", "energy_kwh"},
        )
        self.assertEqual(seed_demo_data(self.database_path, now), 0)
        self.assertEqual(summarize_readings(self.database_path)["reading_count"], 338)

    def test_list_meters_returns_each_meter_latest_reading(self):
        save_reading(
            self.database_path,
            {
                "meter_id": "meter-1",
                "timestamp": "2026-01-01T10:00:00Z",
                "measurements": {"voltage_v": 220},
            },
        )
        save_reading(
            self.database_path,
            {
                "meter_id": "meter-1",
                "timestamp": "2026-01-01T11:00:00Z",
                "measurements": {"voltage_v": 230, "current_a": 5},
            },
        )
        save_reading(
            self.database_path,
            {
                "meter_id": "meter-2",
                "timestamp": "2026-01-01T09:00:00Z",
                "measurements": {"energy_kwh": 100},
            },
        )

        meters = list_meters(self.database_path)

        self.assertEqual([meter["meter_id"] for meter in meters], ["meter-1", "meter-2"])
        self.assertEqual(meters[0]["latest_reading"], "2026-01-01T11:00:00.000000Z")
        self.assertEqual(
            {item["name"]: item["value"] for item in meters[0]["measurements"]},
            {"voltage_v": 230.0, "current_a": 5.0},
        )
        self.assertEqual(len(meters), 2)

    def test_register_meter_with_optional_details(self):
        meter, created = register_meter(
            self.database_path,
            {
                "meter_id": "meter-registered",
                "display_name": "Workshop meter",
                "location": "Workshop",
            },
        )

        self.assertTrue(created)
        self.assertEqual(meter["display_name"], "Workshop meter")
        self.assertEqual(meter["location"], "Workshop")
        self.assertEqual(
            list_meters(self.database_path),
            [
                {
                    "meter_id": "meter-registered",
                    "display_name": "Workshop meter",
                    "location": "Workshop",
                    "registered_at": meter["registered_at"],
                    "latest_reading": None,
                    "measurements": [],
                }
            ],
        )

    def test_initialize_migrates_existing_reading_meter_ids(self):
        legacy_database = Path(self.temp_dir.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_database)) as connection:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE readings (
                        id INTEGER PRIMARY KEY,
                        meter_id TEXT NOT NULL,
                        recorded_at TEXT NOT NULL
                    );
                    CREATE TABLE measurements (
                        reading_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        value REAL NOT NULL,
                        PRIMARY KEY (reading_id, name)
                    );
                    INSERT INTO readings (meter_id, recorded_at)
                    VALUES ('legacy-meter', '2026-01-01T10:00:00Z');
                    """
                )

        initialize_database(legacy_database)

        meters = list_meters(legacy_database)
        self.assertEqual(len(meters), 1)
        self.assertEqual(meters[0]["meter_id"], "legacy-meter")
        self.assertEqual(meters[0]["display_name"], "legacy-meter")
        self.assertEqual(meters[0]["latest_reading"], "2026-01-01T10:00:00Z")

    def test_register_meter_defaults_display_name_and_rejects_duplicates(self):
        meter, created = register_meter(
            self.database_path,
            {"meter_id": "meter-registered"},
        )
        duplicate, duplicate_created = register_meter(
            self.database_path,
            {"meter_id": "meter-registered", "display_name": "Changed name"},
        )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(meter["display_name"], "meter-registered")
        self.assertEqual(duplicate["display_name"], "Changed name")
        self.assertEqual(list_meters(self.database_path)[0]["display_name"], "meter-registered")

    def test_reading_automatically_registers_meter(self):
        save_reading(
            self.database_path,
            {"meter_id": "mqtt-meter", "measurements": {"voltage_v": 230}},
        )

        meter = list_meters(self.database_path)[0]
        self.assertEqual(meter["meter_id"], "mqtt-meter")
        self.assertEqual(meter["display_name"], "mqtt-meter")
        self.assertIsNotNone(meter["latest_reading"])


if __name__ == "__main__":
    unittest.main()
