# Meter Monitor

A Python application that receives meter readings over MQTT, stores them in SQLite, and serves a Flask dashboard with reports and trends.

## Run locally

1. Install Python 3.10 or newer.
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. `.env.example` contains settings for the local demo broker; copy it to `.env` if needed.
4. Seed 7 days of sample data (safe to rerun; it will not duplicate demo readings):

   ```powershell
   python seed_demo_data.py
   ```

5. Install Mosquitto if needed, then ensure its Windows service is running:

   ```powershell
   winget install --id EclipseFoundation.Mosquitto --source winget
   Get-Service mosquitto
   Start-Service mosquitto # only if the service is stopped
   ```

   The installer may already have started the service. If you prefer to run a broker manually instead, stop the service first and start the loopback-only project config:

   ```powershell
   & "C:\Program Files\Mosquitto\mosquitto.exe" -c .\mosquitto-demo.conf -v
   ```

6. Start the app:

   ```powershell
   python app.py
   ```

7. In another terminal, start the demo MQTT publisher:

   ```powershell
   python publish_demo_readings.py
   ```

8. Open <http://127.0.0.1:5000>. Use **All meters** to see registered meters and their latest measurements, or **Add meter** to register a meter before it starts reporting.

The demo publisher sends live readings for every meter registered in SQLite every 5 seconds, including meters added while it is running. It registers two demo meters on startup and picks up any additional meter at the next publish cycle. Each reading includes voltage, current, active power, and energy measurements. The Flask MQTT subscriber listens to `meters/+/readings`, validates each JSON payload, and writes it to the SQLite database. The dashboard and All meters page refresh every 5 seconds to show newly received values. The included manual Mosquitto config listens only on `127.0.0.1` and allows anonymous connections for local development; do not expose this configuration to a network. The SQLite database is created at `instance/meter_readings.sqlite3` by default. Set `DATABASE_PATH` to use another location.

## MQTT message format

Publish JSON readings to the configured topic (default `meters/+/readings`). Each message must include a meter identifier and one or more numeric measurements. `timestamp` is optional; when omitted, the receive time is recorded. Timestamps should be ISO 8601; timezone-naive values are interpreted as UTC.

```json
{
  "meter_id": "meter-001",
  "timestamp": "2026-10-23T06:19:00Z",
  "measurements": {
    "voltage_v": 230.4,
    "current_a": 5.2,
    "active_power_kw": 1.18,
    "energy_kwh": 4821.6
  }
}
```

Measurement names and units depend on the meter and its firmware. Map vendor-specific fields into this generic format in the publisher or add a decoder for the particular meter protocol. Configure `MQTT_USERNAME`, `MQTT_PASSWORD`, and `MQTT_TLS=true` as required by the broker. Do not commit credentials.

The dashboard refreshes every 5 seconds and supports 24-hour, 7-day, 30-day, and all-time views. It shows the number of readings, reporting meters, latest reading, and per-measurement average/latest values and trend charts. Trend points are limited to the most recent 5,000 database measurement rows per view.

The **All meters** page lists registered meters, their latest timestamp and measurements, and refreshes every 5 seconds. Register meters at `/meters/add` with a required meter ID and optional display name and location. IDs must match the `meter_id` in MQTT readings. Meters discovered through incoming readings are registered automatically.

Stop each demo process with Ctrl+C in its terminal. The broker, Flask app, and MQTT publisher run as separate processes.

## Test

```powershell
python -m unittest discover -s tests
```
