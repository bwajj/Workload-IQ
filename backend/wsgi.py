"""Production WSGI entrypoint (gunicorn wsgi:app).

The app boots immediately and trains the model lazily on the first scoring request
(via risk.get_model()), so gunicorn binds the port fast and the host's start
health-check passes. Data is expected to already be in MongoDB (loaded offline).

Set WARM_ON_BOOT=1 to train eagerly in a background thread instead (optional).
"""
import os
import threading

from app import app, ensure_ready

if os.environ.get("WARM_ON_BOOT") == "1":
    threading.Thread(target=ensure_ready, daemon=True).start()

if __name__ == "__main__":
    app.run()
