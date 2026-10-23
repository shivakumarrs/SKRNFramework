import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from meter_mqtt import start_mqtt_subscriber, subscriber_status
from storage import (
    initialize_database,
    list_meters,
    register_meter,
    save_reading,
    summarize_readings,
)

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def create_app():
    app = Flask(__name__)
    instance_path = Path(os.getenv("INSTANCE_PATH", Path(__file__).parent / "instance"))
    instance_path.mkdir(parents=True, exist_ok=True)
    database_path = Path(os.getenv("DATABASE_PATH", instance_path / "meter_readings.sqlite3"))
    initialize_database(database_path)
    app.config["DATABASE_PATH"] = database_path

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/meters")
    def meters_page():
        return render_template("meters.html")

    @app.get("/meters/add")
    def add_meter_page():
        return render_template("add_meter.html")

    @app.get("/api/meters")
    def meters_data():
        meters = list_meters(database_path)
        return jsonify({"meter_count": len(meters), "meters": meters})

    @app.post("/api/meters")
    def add_meter():
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        try:
            meter, created = register_meter(database_path, request.get_json(silent=True))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        if not created:
            return jsonify({"error": f"Meter {meter['meter_id']!r} is already registered"}), 409
        return jsonify({"meter": meter}), 201

    @app.get("/api/dashboard")
    def dashboard_data():
        period = request.args.get("period", "24h")
        periods = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "all": None,
        }
        if period not in periods:
            return jsonify({"error": "period must be one of 24h, 7d, 30d, or all"}), 400

        cutoff = None
        if periods[period] is not None:
            cutoff = (datetime.now(timezone.utc) - periods[period]).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
        summary = summarize_readings(database_path, cutoff)
        summary["mqtt"] = subscriber_status()
        return jsonify(summary)

    return app


app = create_app()


if __name__ == "__main__":
    start_mqtt_subscriber(app.config["DATABASE_PATH"])
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "").lower() == "true",
        use_reloader=False,
    )
