"""Load the simulated dataset into MongoDB (drops and recreates collections)."""
import db
import features as feat
from simulate import simulate, TODAY


def seed():
    data = simulate()
    database = db.get_db()

    for name in ["players", "games", "injuries", "features", "fixtures"]:
        database[name].drop()
    database["current_features"].drop()

    db.players().insert_many(data["players"])
    db.games().insert_many(data["games"])
    db.injuries().insert_many(data["injuries"])
    db.features().insert_many(data["features"])
    database["current_features"].insert_many(data["current_features"])
    db.fixtures().insert_many(data["fixtures"])

    db.ensure_indexes()
    feat.set_reference_date(TODAY, {"dataSource": "simulated"})

    return {name: database[name].count_documents({})
            for name in ["players", "games", "injuries", "features",
                         "current_features", "fixtures"]}


if __name__ == "__main__":
    counts = seed()
    print("Seeded MongoDB:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
