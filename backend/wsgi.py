"""Production WSGI entrypoint (gunicorn wsgi:app).

Runs ensure_ready() once on boot so the model is trained before serving. Data is
expected to already be in MongoDB (ingest offline against the deployment DB); if
the DB is empty and DATA_SOURCE=apifootball it will ingest, which needs the API key.
"""
from app import app, ensure_ready

ensure_ready()

if __name__ == "__main__":
    app.run()
