# ⚕️ Workload IQ — Injury-Risk Analytics for the Premier League

A full-stack analytics platform that correlates player **workload** with
**injury risk**, predicts soft-tissue injuries from workload features, and helps
balance risk against form, fixture difficulty and price when picking a lineup.

**Stack:** React + TypeScript (Vite) · Flask REST API · MongoDB · scikit-learn (gradient boosting)

**Data:** real Premier League data from **API-Football** — **four seasons**
(2022-23 → 2025-26), all competitions (league, domestic cups, Europe,
internationals). 2025-26 is the live view; earlier seasons feed model training and
player history. ~59k player-matches, ~2,600 injuries, 591 current players.

### Pages
- **Today** — every player ranked by 14-day injury risk.
- **Selection** — rotation planner: recommended XI, drag-and-drop swaps, gameweek
  time-travel, fixture difficulty, start confidence.
- **Picks** — league-wide captain shortlist + players to sit for a gameweek.
- **Fixtures** — FPL-style fixture-difficulty ticker (next 6 GWs, all teams).
- **Compare** — 2–3 players head to head.
- **My Team** — import your real FPL squad by Team ID (or build one), see risk /
  confidence / price on a live pitch, drag subs, get transfer suggestions.
- **Evidence** — the backtest (predictions vs. what actually happened), ACWR
  injury curve, model feature importances.
- **Player page** — per-season workload timeline, injury history, what-if simulator.

---

## Real data (API-Football)

The platform ingests real squads, per-match minutes, injuries and fixtures from
[API-Football](https://www.api-football.com/).

1. Put your key in a **gitignored** `backend/.env`:
   ```
   API_FOOTBALL_KEY=your_key_here
   API_FOOTBALL_HOST=v3.football.api-sports.io
   LEAGUE_ID=39
   TARGET_SEASON=2023
   ```
2. Check what your plan can access, then ingest:
   ```bash
   backend/venv/bin/python backend/pipeline.py probe    # plan + season access
   backend/venv/bin/python backend/pipeline.py all      # ingest + build features
   ```
3. Run the app against real data: `DATA_SOURCE=apifootball` (already set in the
   `dev:api` npm script) — `npm run dev`.

Ingestion is **idempotent** (keyed on API-Football IDs) and **cache-backed**
(`backend/.api-cache/`), so re-running refreshes rosters/injuries and resumes
without re-spending API quota. On the **free tier** (~100 req/day), minutes are
only fetched for a recent window of fixtures (`MAX_FIXTURE_DETAIL`, default 60);
a paid key lifts this to a full season. `POST /api/ingest` refreshes on demand.

**Honest modelling note:** on this limited real-data window the learned model's
cross-validated AUC is ~0.43 (below baseline — real injury prediction from
workload alone is genuinely hard). The app **detects this and falls back to the
validated ACWR rule set** for scoring rather than shipping a coin-flip model,
and discloses it in the UI. With a full season of minutes the learned model has
more to work with.

---

## What it does

- **Schema-flexible MongoDB store** for heterogeneous data: per-player **box
  scores** (`games`) and **injury reports** (`injuries`), plus derived
  `features`, `current_features` and upcoming `fixtures`.
- **Multi-stage aggregation pipelines** run *inside* MongoDB:
  - `$lookup` — join `games` ↔ `players` ↔ `injuries`
  - `$setWindowFields` — rolling **7-day acute** and **28-day chronic** workload
    per player (the workload timeline)
  - `$bucket` — injury rate by **ACWR** band, surfacing the workload→injury
    correlation
  - `$group` — squad/team/body-part roll-ups
- **Rolling workload features:** minutes played, rest days, back-to-back
  frequency, matches in last 14 days, acute:chronic workload ratio (ACWR).
- **Injury prediction:** a **logistic-regression** model (scikit-learn) trained
  on labelled player-match rows (features → injured within 14 days) outputs a
  probability, blended with interpretable sports-science rules to tier players
  **Low / Moderate / High**.
- **Rotation planner:** for each team's next fixture, recommends the
  lowest-risk XI (4-3-3), flags high-risk players to rest, and lists injured
  players who are unavailable.
- **React dashboard:** overview + risk board + correlation charts + per-player
  **workload timelines overlaid with injury events** + rotation planner.

> The dataset is **simulated** (deterministic seed). Crucially, injuries are
> *generated from* workload in the model, so the correlations the platform
> surfaces — and the ML signal — are real, not noise. It reproduces the
> well-documented **U-shaped ACWR risk curve** (lowest risk in the 0.8–1.3
> "sweet spot").

## Getting started

Requires **Node 18+** and **Python 3.10+**. MongoDB and the Python venv are
already provisioned in `backend/` by the setup below.

```bash
npm install                        # frontend deps
python3 -m venv backend/venv       # (already created)
backend/venv/bin/pip install -r backend/requirements.txt

npm run dev                        # starts MongoDB + Flask + Vite together
```

Open **http://localhost:5173**. On first boot the API auto-seeds MongoDB and
trains the model. `npm run dev` runs three processes concurrently:

| Process | Port  | Command                                  |
|---------|-------|------------------------------------------|
| mongo   | 27017 | local `mongod` on `backend/.mongo-data`  |
| api     | 5001  | Flask (`backend/app.py`)                 |
| web     | 5173  | Vite dev server (proxies `/api` → 5001)  |

To reseed on demand: `POST /api/seed`.

## Deployment

Three parts, all free-tier friendly:

| Part | Host | Notes |
|------|------|-------|
| MongoDB | **MongoDB Atlas** (M0) | create a cluster, get the `MONGO_URI` |
| Backend | **Render** web service | root `backend/`, `pip install -r requirements.txt`, start from `Procfile` (`gunicorn wsgi:app`) |
| Frontend | **Vercel** | Vite build, SPA rewrite via `vercel.json` |

Steps:
1. **Atlas**: create M0 cluster + DB user, allow-list `0.0.0.0/0`, copy the SRV URI.
2. **Load data into Atlas** (one-off, from your machine, needs the Pro API key):
   `MONGO_URI="<atlas-uri>" backend/venv/bin/python backend/pipeline.py all`
   then `... pipeline.py map-fpl`.
3. **Render**: new Web Service from the GitHub repo, root dir `backend`. Env vars:
   `MONGO_URI`, `API_FOOTBALL_KEY`, `API_FOOTBALL_HOST`, `AUTH_SECRET`,
   `DATA_SOURCE=apifootball`, `INGEST_SEASONS`, `SMTP_*`, `MAIL_FROM`,
   `APP_URL=<vercel-url>`. It boots `gunicorn wsgi:app` (trains the model on start).
4. **Vercel**: import the repo, framework Vite. Env var `VITE_API_URL=<render-url>`.
   Redeploy so the frontend calls the Render API.

Secrets are never committed (`.env`, keys, caches are gitignored) — set them in each
host's dashboard. Local chat/transcript files live outside the repo and are not deployed.

## Fantasy Premier League link

Live in **My Team**: paste your FPL **Team ID** (from your FPL URL,
`fantasy.premierleague.com/entry/{ID}/…`, no login) and your squad is fetched,
mapped to our players, and scored.

- The **official FPL API is public/read-only** (`backend/fpl.py`).
- Entity resolution: `build_player_map()` fuzzy-matches (team + name,
  unique-candidate only) and persists an `fplId → our id` table (with FPL price)
  in the `player_map` collection — run `python backend/pipeline.py map-fpl`.
- Because the data is now on the season the FPL API serves, **~96% of a squad's
  real players map**; the few misses (fringe players with no minutes) are shown
  honestly as "no data".

## Email (welcome / transactional)

Registration sends a welcome email via `backend/mailer.py`. **Without SMTP
configured it falls back to writing `.eml` files to `backend/outbox/`** — so the
flow is always inspectable locally and never silently drops mail.

To send for real, add these to the gitignored `backend/.env` (example uses
[Brevo](https://www.brevo.com), free tier ≈ 300 emails/day):

```
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<Brevo SMTP login, e.g. 8xxxxxx@smtp-brevo.com>
SMTP_PASS=<Brevo SMTP key — not your account password>
MAIL_FROM=Workload IQ <sender@yourdomain.com>   # must be a Brevo-verified sender
APP_URL=http://localhost:5173
```

Setup notes:
- **`MAIL_FROM` must be a sender you've verified in Brevo** (Senders & Domains),
  or the send is rejected. `mailer.py` reads `.env` at import — restart the API
  after changing it.
- Brevo may enforce **Authorized IPs** (Security settings); a `525 Unauthorized
  IP address` error means your current IP isn't allowlisted.
- **Deliverability:** sending from a `@gmail.com` (or other free-mailbox) address
  lands in **spam**, because SPF/DKIM can't align for a domain you don't control.
  For reliable inbox delivery, authenticate a domain you own in Brevo and send
  from `no-reply@yourdomain.com` — no code change, just `MAIL_FROM`.
- Quick test: `backend/venv/bin/python -c "import mailer;
  print(mailer.send_welcome('you@example.com','You'))"` prints `smtp` on a real
  send, `outbox` on the local fallback.

## Data refresh (scheduled)

`backend/refresh.py` re-ingests, rebuilds features, retrains, and stamps
`meta.lastRefresh` (surfaced in `/api/health` and the app masthead). A file lock
skips overlapping runs. Schedule it (cron/launchd) on a live season:

```bash
0 6 * * *  cd /path/backend && venv/bin/python refresh.py   # daily 6am
```

Honest caveat: on a **completed** season this re-fetches the same cached data —
the value is mid-season, when new injuries / lineups / transfers land. A running
API server picks up refreshed data on its next model reload (restart or
`POST /api/ingest`).

## Tests

Pure-logic unit tests cover the workload feature engineering, risk scoring,
injury-history signals, start-confidence, and the ingest mapping helpers — no
database or network needed. Run them from `backend/`:

```bash
backend/venv/bin/pytest -q      # 32 tests
```

CI (`.github/workflows/ci.yml`) runs the backend tests plus the frontend
typecheck and production build on every push / PR.

## API reference (`/api`)

| Method | Path                          | Description                                   |
|--------|-------------------------------|-----------------------------------------------|
| GET    | `/health`                     | Liveness + Mongo/model status + `lastRefresh` |
| GET    | `/overview`                   | Counts, model AUC, risk-tier split, top risk  |
| GET    | `/players?team=`              | All players scored (risk, confidence, price)  |
| GET    | `/players/<id>`               | Profile, risk breakdown, multi-season timeline, injuries |
| GET    | `/rotation/<team>?gameweek=`  | Recommended XI + rest/unavailable + squad     |
| GET    | `/gameweeks`                  | Selectable gameweeks (planner/backtest)       |
| GET    | `/picks?gameweek=`            | Captain shortlist + players to sit            |
| GET    | `/fixture-ticker?n=&fromRound=` | Difficulty grid, 20 teams × N gameweeks     |
| GET    | `/transfers?playerId=`        | Replacement suggestions (same pos, ≤+£0.5m)   |
| GET    | `/backtest?gameweek=`         | Predictions vs. actual injuries               |
| GET    | `/correlation`                | `$bucket` ACWR injury rates, feature importances, body parts |
| GET    | `/injuries?team=`             | Injury reports                                |
| POST   | `/fpl`                        | Resolve an FPL Team ID → scored squad         |
| POST   | `/auth/{login,register,me,fpl-team}` | Auth + save FPL team                   |
| POST   | `/digest/send`                | Email the gameweek digest                     |
| POST   | `/ingest`                     | Re-ingest, rebuild features, retrain          |

## Project structure

```
backend/
  app.py          Flask routes + JSON serialization + startup
  wsgi.py         Production entrypoint (gunicorn wsgi:app)
  db.py           Mongo connection, collections, indexes
  apifootball.py  Rate-limited, cached API-Football client
  ingest.py       Multi-season ingest (league + cups + Europe + internationals)
  features.py     Rolling workload + injury-history feature engineering
  risk.py         Gradient-boosted model, tiering, confidence, picks, rotation
  fpl.py          FPL client + player-id mapping
  pipelines.py    Aggregation pipelines ($lookup / $bucket / $group / $setWindowFields)
  refresh.py      Scheduled re-ingest
  tests/          pytest suite
src/
  pages/          Today, Selection, Picks, Fixtures, Compare, MyTeam, Evidence, PlayerDetail, Landing, Login
  api.ts          Typed fetch client (VITE_API_URL base)
  types.ts        Shared types
  ui.tsx          Shared components (photos, crests, chart theme)
```

## Modelling notes

- **Target**: soft-tissue (non-contact) injuries within 14 days — the injuries
  workload actually predicts, not impact/collision ones.
- **Features**: ACWR (acute 7-day ÷ chronic 28-day load), 3-/21-day load, rest,
  congestion, back-to-backs, age, plus injury history (return-to-play recency,
  prior-injury count) and career games.
- **Model**: `HistGradientBoosting`, validated with **GroupKFold by player** (no
  player in both train and test) — honest **ROC-AUC ≈ 0.64**. Only shipped if it
  beats baseline; otherwise falls back to interpretable ACWR rules.
- **Start confidence** (0–100) fuses risk, form, fatigue and fixture difficulty
  into one number for lineup decisions.
