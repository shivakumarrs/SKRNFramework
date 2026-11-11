import json
import threading
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import paho.mqtt.client as mqtt

from publish_demo_readings import publish_demo_cycle
from storage import initialize_database, list_meters, register_meter


class PublishedMessage:
    rc = mqtt.MQTT_ERR_SUCCESS

    def wait_for_publish(self, timeout):
        self.timeout = timeout

    def is_published(self):
        return True


class FakeMqttClient:
    def __init__(self):
        self.messages = []
        self.connected = True

    def publish(self, topic, payload, qos):
        self.messages.append(
            {"topic": topic, "payload": json.loads(payload), "qos": qos}
        )
        return PublishedMessage()

    def is_connected(self):
        return self.connected


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

    def test_publish_retries_after_connection_drops(self):
        register_meter(self.database_path, {"meter_id": "meter-reconnect"})
        client = FakeMqttClient()
        connected = threading.Event()
        disconnected = threading.Event()
        connected.set()
        publish = client.publish
        calls = 0

        def disconnect_once(topic, payload, qos):
            nonlocal calls
            calls += 1
            if calls == 1:
                client.connected = False
                connected.clear()
                disconnected.set()
                raise RuntimeError("The client is not currently connected.")
            return publish(topic, payload, qos)

        client.publish = disconnect_once

        def reconnect():
            disconnected.wait(timeout=2)
            client.connected = True
            connected.set()

        reconnect_thread = threading.Thread(target=reconnect)
        reconnect_thread.start()
        with patch("publish_demo_readings.time.sleep", side_effect=lambda _delay: None):
            count = publish_demo_cycle(
                client,
                self.database_path,
                sample_index=0,
                timestamp="2026-10-23T12:00:00Z",
                connected=connected,
            )
        reconnect_thread.join(timeout=2)

        self.assertEqual(count, 1)
        self.assertEqual(calls, 2)
        self.assertEqual(len(client.messages), 1)


if __name__ == "__main__":
    unittest.main()
