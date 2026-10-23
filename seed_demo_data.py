import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage import initialize_database, save_reading


def seed_demo_data(database_path, now=None):
    initialize_database(database_path)
    with closing(sqlite3.connect(database_path)) as connection:
        exists = connection.execute(
            "SELECT 1 FROM readings WHERE meter_id LIKE 'demo-meter-%' LIMIT 1"
        ).fetchone()
    if exists:
        return 0

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )

    count = 0
    for hours_ago in range(7 * 24, -1, -1):
        recorded_at = current_time - timedelta(hours=hours_ago)
        elapsed_hours = 7 * 24 - hours_ago
        for meter_index in range(2):
            phase = meter_index * 0.8
            voltage = 230 + 2.2 * math.sin(hours_ago / 5 + phase)
            current = 4.5 + 1.1 * math.sin(hours_ago / 7 + phase)
            active_power = voltage * current * 0.9 / 1000
            energy = 4820 + meter_index * 725 + elapsed_hours * active_power
            save_reading(
                database_path,
                {
                    "meter_id": f"demo-meter-{meter_index + 1:03}",
                    "timestamp": recorded_at.isoformat(),
                    "measurements": {
                        "voltage_v": round(voltage, 2),
                        "current_a": round(current, 2),
                        "active_power_kw": round(active_power, 3),
                        "energy_kwh": round(energy, 2),
                    },
                },
            )
            count += 1
    return count


if __name__ == "__main__":
    import os

    database_path = Path(
        os.getenv(
            "DATABASE_PATH",
            Path(__file__).parent / "instance" / "meter_readings.sqlite3",
        )
    )
    inserted = seed_demo_data(database_path)
    print(f"Inserted {inserted} demo readings into {database_path}")
