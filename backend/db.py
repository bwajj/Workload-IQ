"""MongoDB connection and collection helpers.

The store is intentionally schema-flexible: `games` holds heterogeneous
per-player box-score documents and `injuries` holds injury-report documents
whose fields vary by injury type. Mongo's document model fits this naturally.
"""
import os
from pymongo import MongoClient, ASCENDING

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "pl_injury")

_client = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
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
