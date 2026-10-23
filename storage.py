import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def initialize_database(database_path):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY,
                    meter_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS measurements (
                    reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    PRIMARY KEY (reading_id, name)
                );
                CREATE TABLE IF NOT EXISTS meters (
                    meter_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    location TEXT,
                    registered_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO meters (meter_id, display_name, registered_at)
                SELECT meter_id, meter_id, MIN(recorded_at)
                FROM readings
                GROUP BY meter_id;
                CREATE INDEX IF NOT EXISTS idx_readings_recorded_at
                    ON readings(recorded_at);
                CREATE INDEX IF NOT EXISTS idx_readings_meter_id
                    ON readings(meter_id);
                CREATE INDEX IF NOT EXISTS idx_measurements_name
                    ON measurements(name);
                """
            )


def normalize_reading(payload):
    if not isinstance(payload, dict):
        raise ValueError("reading must be a JSON object")

    meter_id = payload.get("meter_id")
    if not isinstance(meter_id, str) or not meter_id.strip():
        raise ValueError("meter_id must be a non-empty string")
    meter_id = meter_id.strip()
    if len(meter_id) > 128:
        raise ValueError("meter_id must be 128 characters or fewer")

    measurements = payload.get("measurements")
    if not isinstance(measurements, dict) or not measurements:
        raise ValueError("measurements must be a non-empty object")
    if len(measurements) > 100:
        raise ValueError("a reading may contain at most 100 measurements")

    normalized_measurements = {}
    for name, value in measurements.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("measurement names must be non-empty strings of at most 80 characters")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"measurement {name!r} must be numeric")
        normalized_name = name.strip()
        if normalized_name in normalized_measurements:
            raise ValueError(f"duplicate measurement name after trimming: {normalized_name!r}")
        try:
            numeric_value = float(value)
        except OverflowError as error:
            raise ValueError(f"measurement {name!r} is outside the supported numeric range") from error
        if not math.isfinite(numeric_value):
            raise ValueError(f"measurement {name!r} must be finite")
        normalized_measurements[normalized_name] = numeric_value

    timestamp = payload.get("timestamp")
    if timestamp is None:
        recorded_at = datetime.now(timezone.utc)
    elif isinstance(timestamp, str):
        try:
            recorded_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("timestamp must be an ISO 8601 datetime") from error
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        recorded_at = recorded_at.astimezone(timezone.utc)
    else:
        raise ValueError("timestamp must be an ISO 8601 string")

    return {
        "meter_id": meter_id,
        "recorded_at": recorded_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "measurements": normalized_measurements,
    }


def save_reading(database_path, payload):
    reading = normalize_reading(payload)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO meters (meter_id, display_name, registered_at)
                VALUES (?, ?, ?)
                """,
                (
                    reading["meter_id"],
                    reading["meter_id"],
                    reading["recorded_at"],
                ),
            )
            cursor = connection.execute(
                "INSERT INTO readings (meter_id, recorded_at) VALUES (?, ?)",
                (reading["meter_id"], reading["recorded_at"]),
            )
            connection.executemany(
                "INSERT INTO measurements (reading_id, name, value) VALUES (?, ?, ?)",
                [
                    (cursor.lastrowid, name, value)
                    for name, value in reading["measurements"].items()
                ],
            )
    return reading


def register_meter(database_path, payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    meter_id = payload.get("meter_id")
    if not isinstance(meter_id, str) or not meter_id.strip():
        raise ValueError("meter_id must be a non-empty string")
    meter_id = meter_id.strip()
    if len(meter_id) > 128:
        raise ValueError("meter_id must be 128 characters or fewer")

    display_name = payload.get("display_name", "")
    if not isinstance(display_name, str):
        raise ValueError("display_name must be a string")
    display_name = display_name.strip() or meter_id
    if len(display_name) > 128:
        raise ValueError("display_name must be 128 characters or fewer")

    location = payload.get("location", "")
    if not isinstance(location, str):
        raise ValueError("location must be a string")
    location = location.strip() or None
    if location is not None and len(location) > 128:
        raise ValueError("location must be 128 characters or fewer")

    registered_at = datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO meters
                    (meter_id, display_name, location, registered_at)
                VALUES (?, ?, ?, ?)
                """,
                (meter_id, display_name, location, registered_at),
            )
            created = cursor.rowcount == 1

    return {
        "meter_id": meter_id,
        "display_name": display_name,
        "location": location,
        "registered_at": registered_at,
    }, created


def summarize_readings(database_path, cutoff=None):
    condition = "WHERE r.recorded_at >= ?" if cutoff else ""
    parameters = (cutoff,) if cutoff else ()
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.row_factory = sqlite3.Row
            counts = connection.execute(
                f"""
                SELECT COUNT(*) AS reading_count,
                       COUNT(DISTINCT meter_id) AS meter_count,
                       MAX(recorded_at) AS latest_reading
                FROM readings AS r
                {condition}
                """,
                parameters,
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT r.id, r.meter_id, r.recorded_at, m.name, m.value
                FROM readings AS r
                JOIN measurements AS m ON m.reading_id = r.id
                {condition}
                ORDER BY r.recorded_at DESC, r.id DESC
                LIMIT 5000
                """,
                parameters,
            ).fetchall()

    readings = {}
    for row in reversed(rows):
        reading = readings.setdefault(
            row["id"],
            {
                "meter_id": row["meter_id"],
                "timestamp": row["recorded_at"],
                "measurements": {},
            },
        )
        reading["measurements"][row["name"]] = row["value"]

    values_by_metric = {}
    for reading in readings.values():
        for name, value in reading["measurements"].items():
            values_by_metric.setdefault(name, []).append(
                {
                    "timestamp": reading["timestamp"],
                    "meter_id": reading["meter_id"],
                    "value": value,
                }
            )

    metrics = []
    for name, points in sorted(values_by_metric.items()):
        metrics.append(
            {
                "name": name,
                "average": sum(point["value"] for point in points) / len(points),
                "latest": points[-1]["value"],
                "points": points,
            }
        )

    return {
        "reading_count": counts["reading_count"],
        "meter_count": counts["meter_count"],
        "latest_reading": counts["latest_reading"],
        "metrics": metrics,
    }


def list_meters(database_path):
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                WITH ranked_readings AS (
                    SELECT id, meter_id, recorded_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY meter_id
                               ORDER BY recorded_at DESC, id DESC
                           ) AS rank
                    FROM readings
                )
                SELECT registered.meter_id, registered.display_name,
                       registered.location, registered.registered_at,
                       latest.recorded_at, measurement.name, measurement.value
                FROM meters AS registered
                LEFT JOIN ranked_readings AS latest
                    ON latest.meter_id = registered.meter_id AND latest.rank = 1
                LEFT JOIN measurements AS measurement
                    ON measurement.reading_id = latest.id
                ORDER BY latest.recorded_at DESC, registered.display_name, registered.meter_id
                """
            ).fetchall()

    meters = {}
    for row in rows:
        meter = meters.setdefault(
            row["meter_id"],
            {
                "meter_id": row["meter_id"],
                "display_name": row["display_name"],
                "location": row["location"],
                "registered_at": row["registered_at"],
                "latest_reading": row["recorded_at"],
                "measurements": [],
            },
        )
        if row["name"] is not None:
            meter["measurements"].append(
                {"name": row["name"], "value": row["value"]}
            )
    return list(meters.values())
