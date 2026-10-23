import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from storage import initialize_database, list_meters, register_meter

load_dotenv()


def build_demo_reading(meter_id, sample_index, timestamp=None):
    meter_seed = sum((index + 1) * ord(character) for index, character in enumerate(meter_id))
    phase = (meter_seed % 6283) / 1000
    voltage = 230 + 2.2 * math.sin(sample_index / 4 + phase)
    current = 4.5 + 1.1 * math.sin(sample_index / 6 + phase)
    power = voltage * current * 0.9 / 1000
    energy_start = 4000 + meter_seed % 3000
    return {
        "meter_id": meter_id,
        "timestamp": timestamp
        or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "measurements": {
            "voltage_v": round(voltage, 2),
            "current_a": round(current, 2),
            "active_power_kw": round(power, 3),
            "energy_kwh": round(energy_start + sample_index * power / 720, 2),
        },
    }


def publish_demo_cycle(client, database_path, sample_index, timestamp=None):
    meters = list_meters(database_path)
    for meter in meters:
        meter_id = meter["meter_id"]
        reading = build_demo_reading(meter_id, sample_index, timestamp)
        topic = f"meters/{quote(meter_id, safe='')}/readings"
        info = client.publish(topic, json.dumps(reading), qos=1)
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise RuntimeError(f"Timed out publishing a reading for {meter_id}")
        print(f"{reading['timestamp']}  {meter_id}  {reading['measurements']['active_power_kw']:.3f} kW")
    return len(meters)


def main():
    parser = argparse.ArgumentParser(
        description="Publish simulated readings for every registered meter."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("MQTT_DEMO_INTERVAL_SECONDS", "5")),
        help="seconds between readings (default: 5)",
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    host = os.getenv("MQTT_HOST", "127.0.0.1")
    port = int(os.getenv("MQTT_PORT", "1883"))
    instance_path = Path(os.getenv("INSTANCE_PATH", Path(__file__).parent / "instance"))
    database_path = Path(os.getenv("DATABASE_PATH", instance_path / "meter_readings.sqlite3"))
    initialize_database(database_path)
    for meter_number in range(1, 3):
        meter_id = f"demo-meter-{meter_number:03}"
        register_meter(
            database_path,
            {"meter_id": meter_id, "display_name": f"Demo Meter {meter_number}"},
        )

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="meter-demo-publisher",
    )
    username = os.getenv("MQTT_USERNAME", "")
    if username:
        client.username_pw_set(username, os.getenv("MQTT_PASSWORD", ""))

    client.connect(host, port, keepalive=60)
    client.loop_start()
    sample_index = 0
    print(
        f"Publishing readings for all registered meters to {host}:{port} "
        f"every {args.interval:g}s. Newly registered meters are picked up automatically. "
        "Press Ctrl+C to stop."
    )

    try:
        while True:
            publish_demo_cycle(client, database_path, sample_index)
            sample_index += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopping demo publisher.")
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
