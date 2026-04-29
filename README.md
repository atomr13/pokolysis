# Pokolysis

A personal football match analysis and prediction workbench. Pulls real data from Sofascore, runs a weighted probability model, and lets you layer in your own observations to produce two probability outputs: **data-only** vs **data + your insight**.

Every prediction is logged against the actual result so your accuracy improves over time.

---

## Features

- **Live match feed** — Premier League, Champions League, Süper Lig, FA Cup, Eliteserien with real-time updates
- **Pre-match analysis** — season stats, form, xG, head-to-head, goal timing by half, referee card stats, injuries
- **Probability model** — weighted formula across PPG, xG differential, recent form, H2H, home advantage
- **AI analysis** — Claude reads your notes and shifts the probability based on what the data can't see
- **Halftime recalculation** — blends HT conditional probabilities with pre-match quality at the break
- **Live stats panel** — all 7 stat groups across All / 1st Half / 2nd Half periods
- **Lineups** — starting XI on a pitch view with ratings, substitutes
- **Prediction history** — your average analysis score tracked over time

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+ · FastAPI · SQLite |
| Frontend | React 19 · Vite |
| AI | Anthropic Claude API |
| Data | Sofascore (unofficial API) |

---

## Setup

### 1. Clone

```bash
git clone https://github.com/atomr13/pokolysis.git
cd pokolysis
```

### 2. Backend

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Run

```bash
chmod +x start.sh
./start.sh
```

Opens at `http://localhost:5173`. Backend runs on port 8002.

---

## Project Structure

```
pokolysis/
├── backend/
│   ├── main.py          # FastAPI routes
│   ├── sofascore.py     # Sofascore API client
│   ├── ml_engine.py     # Probability model
│   ├── ai_analyst.py    # Claude API integration
│   └── database.py      # SQLite schema + helpers
├── frontend/
│   └── src/
│       └── components/
│           ├── MatchFeed.jsx
│           ├── AnalysisPane.jsx
│           ├── TopBar.jsx
│           └── UserMenu.jsx
├── start.sh
└── README.md
```

---

## Notes

- Sofascore API: always include a 1s delay between requests — rate limiting is enforced in `sofascore.py`
- The backend runs on port **8002** to avoid conflicts with other local services
- Default user nickname is `analyst` — update it directly in the SQLite database after first run
- Season IDs change each year; the app fetches them dynamically if a 404 is encountered

---

## Competitions

| Key | Name |
|---|---|
| `premier_league` | Premier League |
| `champions_league` | UEFA Champions League |
| `super_lig` | Turkish Süper Lig |
| `fa_cup` | FA Cup |
| `eliteserien` | Norwegian Eliteserien |
