"""MongoDB connection and collection helpers.

The store is intentionally schema-flexible: `games` holds heterogeneous
per-player box-score documents and `injuries` holds injury-report documents
whose fields vary by injury type. Mongo's document model fits this naturally.
"""
import os
import certifi
from pymongo import MongoClient, ASCENDING

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "pl_injury")

_client = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        kwargs = {"serverSelectionTimeoutMS": 3000}
        # Atlas (mongodb+srv / TLS) needs a CA bundle; certifi ships one so it
        # works regardless of the OS's system certs.
        if MONGO_URI.startswith("mongodb+srv") or "mongodb.net" in MONGO_URI:
            kwargs["tlsCAFile"] = certifi.where()
        _client = MongoClient(MONGO_URI, **kwargs)
    return _client


def get_db():
    return get_client()[DB_NAME]


# Collection accessors -----------------------------------------------------

def players():
    return get_db()["players"]


def games():
    return get_db()["games"]


def injuries():
    return get_db()["injuries"]


def features():
    return get_db()["features"]


def fixtures():
    return get_db()["fixtures"]


def users():
    return get_db()["users"]


def ensure_indexes():
    players().create_index([("team", ASCENDING)])
    games().create_index([("playerId", ASCENDING), ("date", ASCENDING)])
    games().create_index([("team", ASCENDING), ("date", ASCENDING)])
    injuries().create_index([("playerId", ASCENDING)])
    injuries().create_index([("team", ASCENDING)])
    features().create_index([("playerId", ASCENDING), ("date", ASCENDING)])
    fixtures().create_index([("team", ASCENDING), ("date", ASCENDING)])


def ping() -> bool:
    """Return True if MongoDB is reachable."""
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False


def ping_debug() -> dict:
    scheme = MONGO_URI.split("://", 1)[0] if "://" in MONGO_URI else "?"
    host = MONGO_URI.rsplit("@", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    err = None
    try:
        get_client().admin.command("ping")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
    return {"scheme": scheme, "host": host, "hasUri": bool(os.environ.get("MONGO_URI")), "error": err}
