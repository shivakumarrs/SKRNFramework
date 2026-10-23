import json
import tempfile
import unittest
from pathlib import Path

from publish_demo_readings import publish_demo_cycle
from storage import initialize_database, list_meters, register_meter


class PublishedMessage:
    def wait_for_publish(self, timeout):
        self.timeout = timeout

    def is_published(self):
        return True


class FakeMqttClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos):
        self.messages.append(
            {"topic": topic, "payload": json.loads(payload), "qos": qos}
        )
        return PublishedMessage()


class DemoPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "readings.sqlite3"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_each_publish_cycle_picks_up_newly_registered_meters(self):
        register_meter(self.database_path, {"meter_id": "demo-meter-001"})
        client = FakeMqttClient()

        first_count = publish_demo_cycle(
            client,
            self.database_path,
            sample_index=0,
            timestamp="2026-10-23T12:00:00Z",
        )
        register_meter(
            self.database_path,
            {"meter_id": "new-meter", "display_name": "New meter"},
        )
        second_count = publish_demo_cycle(
            client,
            self.database_path,
            sample_index=1,
            timestamp="2026-10-23T12:00:05Z",
        )

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 2)
        self.assertEqual(client.messages[0]["payload"]["meter_id"], "demo-meter-001")
        self.assertEqual(
            {message["payload"]["meter_id"] for message in client.messages[1:]},
            {"demo-meter-001", "new-meter"},
        )
        new_meter_message = next(
            message
            for message in client.messages[1:]
            if message["payload"]["meter_id"] == "new-meter"
        )
        self.assertEqual(new_meter_message["topic"], "meters/new-meter/readings")
        self.assertEqual(new_meter_message["qos"], 1)
        self.assertEqual(
            set(new_meter_message["payload"]["measurements"]),
            {"voltage_v", "current_a", "active_power_kw", "energy_kwh"},
        )
        self.assertEqual(
            {meter["meter_id"] for meter in list_meters(self.database_path)},
            {"demo-meter-001", "new-meter"},
        )

    def test_meter_id_is_encoded_as_a_single_mqtt_topic_level(self):
        register_meter(self.database_path, {"meter_id": "floor/one"})
        client = FakeMqttClient()

        publish_demo_cycle(
            client,
            self.database_path,
            sample_index=0,
            timestamp="2026-10-23T12:00:00Z",
        )

        self.assertEqual(client.messages[0]["topic"], "meters/floor%2Fone/readings")


if __name__ == "__main__":
    unittest.main()
