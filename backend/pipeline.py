"""CLI to run the real-data pipeline.

Usage:
    python pipeline.py probe      # inspect API-Football plan + season access
    python pipeline.py ingest     # pull API-Football data into MongoDB
    python pipeline.py features   # (re)build feature collections from Mongo
    python pipeline.py map-fpl    # build the FPL id → our-id mapping (needs network)
    python pipeline.py all        # ingest + features
"""
import sys


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "probe":
        import apifootball as af
        af.probe()
        return

    if cmd == "map-fpl":
        import fpl
        print("FPL player map:", fpl.build_player_map())
        return

    if cmd in ("ingest", "all"):
        import ingest
        counts = ingest.ingest()
        print("\nIngest:", counts)

    if cmd in ("features", "all"):
        import features as feat
        result = feat.compute_features()
        print("Features:", result)

    if cmd not in ("probe", "ingest", "features", "map-fpl", "all"):
        print(__doc__)


if __name__ == "__main__":
    main()
