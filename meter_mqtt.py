import json
import logging
import os
import sqlite3
import threading

import paho.mqtt.client as mqtt

from storage import save_reading

logger = logging.getLogger(__name__)
_status_lock = threading.Lock()
_status = {
    "configured": False,
    "connected": False,
    "topic": None,
    "message": "MQTT is not configured",
}


def subscriber_status():
    with _status_lock:
        return dict(_status)


def start_mqtt_subscriber(database_path):
    host = os.getenv("MQTT_HOST", "").strip()
    if not host:
        logger.info("MQTT_HOST is empty; MQTT ingestion is disabled")
        return None

    port = int(os.getenv("MQTT_PORT", "1883"))
    topic = os.getenv("MQTT_TOPIC", "meters/+/readings")
    client_id = os.getenv("MQTT_CLIENT_ID", "meter-dashboard")
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")

    with _status_lock:
        _status.update(
            {"configured": True, "connected": False, "topic": topic, "message": "Connecting"}
        )

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )
    if username:
        client.username_pw_set(username, password)
    if os.getenv("MQTT_TLS", "").lower() == "true":
        client.tls_set()

    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            message = f"Broker rejected connection: {reason_code}"
            with _status_lock:
                _status.update({"connected": False, "message": message})
            logger.error(message)
            return
        result, _mid = mqtt_client.subscribe(topic)
        if result != mqtt.MQTT_ERR_SUCCESS:
            message = f"Could not subscribe to MQTT topic {topic!r}: result {result}"
            with _status_lock:
                _status.update({"connected": False, "message": message})
            logger.error(message)
            return
        with _status_lock:
            _status.update({"connected": True, "message": "Connected"})
        logger.info("Connected to MQTT broker %s:%s; subscribed to %s", host, port, topic)

    def on_disconnect(_mqtt_client, _userdata, _disconnect_flags, reason_code, _properties):
        message = f"Disconnected ({reason_code})"
        with _status_lock:
            _status.update({"connected": False, "message": message})
        logger.warning("MQTT %s", message)

    def on_connect_fail(_mqtt_client, _userdata):
        message = f"Could not connect to MQTT broker at {host}:{port}"
        with _status_lock:
            _status.update({"connected": False, "message": message})
        logger.error(message)

    def on_message(_mqtt_client, _userdata, message):
        if len(message.payload) > 256 * 1024:
            logger.warning("Ignoring oversized MQTT message on %s", message.topic)
            return
        try:
            payload = json.loads(message.payload)
            save_reading(database_path, payload)
        except (UnicodeDecodeError, ValueError) as error:
            logger.warning("Ignoring invalid reading on %s: %s", message.topic, error)
        except sqlite3.Error:
            logger.exception("Failed to store MQTT reading from %s", message.topic)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_connect_fail = on_connect_fail
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    client.connect_async(host, port, keepalive=60)
    client.loop_start()
    return client
