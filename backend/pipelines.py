"""MongoDB aggregation pipelines.

These run inside MongoDB (not in Python) and are the analytical core of the
platform: joining heterogeneous collections with $lookup, computing rolling
workload features with $setWindowFields, bucketing with $bucket to surface the
workload/injury correlation, and rolling everything up with $group.
"""


def player_workload_summary():
    """Per-player workload + injury summary via $lookup ($group + join)."""
    return [
        {"$group": {
            "_id": "$playerId",
            "playerName": {"$first": "$playerName"},
            "team": {"$first": "$team"},
            "position": {"$first": "$position"},
            "appearances": {"$sum": 1},
            "totalMinutes": {"$sum": "$minutes"},
            "totalDistanceKm": {"$sum": "$distanceKm"},
            "starts": {"$sum": {"$cond": ["$started", 1, 0]}},
        }},
        # Join in that player's injury reports.
        {"$lookup": {
            "from": "injuries",
            "localField": "_id",
            "foreignField": "playerId",
            "as": "injuries",
        }},
        {"$addFields": {
            "injuryCount": {"$size": "$injuries"},
            "daysOutTotal": {"$sum": "$injuries.daysOut"},
        }},
        {"$project": {"injuries": 0}},
        {"$sort": {"totalMinutes": -1}},
    ]


def injury_rate_by_acwr_bucket():
    """$bucket feature rows by ACWR band, computing the injury rate in each.

    This is the headline correlation: it demonstrates how injury onset within
    14 days rises outside the acute:chronic 'sweet spot'.
    """
    return [
        {"$bucket": {
            "groupBy": "$acwr",
            "boundaries": [0, 0.8, 1.0, 1.3, 1.5, 2.0, 100],
            "default": "other",
            "output": {
                "samples": {"$sum": 1},
                "injuries": {"$sum": "$injuredNext14"},
                "avgAcute": {"$avg": "$acute7"},
            },
        }},
        {"$addFields": {
            "injuryRate": {"$cond": [
                {"$eq": ["$samples", 0]}, 0,
                {"$divide": ["$injuries", "$samples"]},
            ]},
        }},
    ]


def team_load_ranking():
    """$group games by team to rank squad workload, $lookup active injuries."""
    return [
        {"$group": {
            "_id": "$team",
            "totalMinutes": {"$sum": "$minutes"},
            "matches": {"$addToSet": "$date"},
            "avgDistanceKm": {"$avg": "$distanceKm"},
        }},
        {"$addFields": {"matchCount": {"$size": "$matches"}}},
        {"$lookup": {
            "from": "injuries",
            "let": {"team": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$team", "$$team"]},
                    {"$eq": ["$status", "Active"]},
                ]}}},
                {"$count": "n"},
            ],
            "as": "activeInj",
        }},
        {"$addFields": {
            "activeInjuries": {"$ifNull": [{"$first": "$activeInj.n"}, 0]},
        }},
        {"$project": {"matches": 0, "activeInj": 0}},
        {"$sort": {"totalMinutes": -1}},
    ]


def player_rolling_timeline(player_id):
    """$setWindowFields: rolling 7-day (acute) & 28-day (chronic) minutes for
    one player, sorted by match date — the workload timeline series."""
    return [
        {"$match": {"playerId": player_id}},
        {"$sort": {"date": 1}},
        {"$setWindowFields": {
            "partitionBy": "$playerId",
            "sortBy": {"date": 1},
            "output": {
                "acute7": {
                    "$sum": "$minutes",
                    "window": {"range": [-6, 0], "unit": "day"},
                },
                "chronic28Total": {
                    "$sum": "$minutes",
                    "window": {"range": [-27, 0], "unit": "day"},
                },
            },
        }},
        {"$addFields": {
            "chronic28": {"$divide": ["$chronic28Total", 4]},
            "acwr": {"$cond": [
                {"$lt": [{"$divide": ["$chronic28Total", 4]}, 30]}, 1.0,
                {"$round": [{"$divide": [
                    "$acute7", {"$divide": ["$chronic28Total", 4]}]}, 3]},
            ]},
        }},
        {"$project": {
            "_id": 0, "date": 1, "minutes": 1, "opponent": 1, "home": 1,
            "started": 1, "competition": 1, "season": 1, "acute7": 1,
            "chronic28": {"$round": ["$chronic28", 1]}, "acwr": 1,
        }},
    ]


def injuries_by_body_part():
    """$group injuries by body part for the breakdown chart."""
    return [
        {"$group": {
            "_id": "$bodyPart",
            "count": {"$sum": 1},
            "avgDaysOut": {"$avg": "$daysOut"},
            "avgAcwrAtOnset": {"$avg": "$acwrAtOnset"},
        }},
        {"$sort": {"count": -1}},
    ]
