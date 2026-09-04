import threading
import requests
from app.config import settings

_stop_flag = threading.Event()
# Serializes demo reset / ingest-fresh against live ingest (including the poller).
ingestion_lock = threading.Lock()

def _poll_loop():
    while not _stop_flag.is_set():
        try:
            # Lock is held inside ingest-live; do not hold it across the HTTP call
            # or we deadlock with the request handler on the same process.
            requests.post("http://localhost:8000/api/v1/commitments/ingest-live", timeout=60)
        except Exception:
            pass
        _stop_flag.wait(settings.poll_interval_seconds)

def start_background_poller():
    if settings.email_mode == "live":
        thread = threading.Thread(target=_poll_loop, daemon=True)
        thread.start()
