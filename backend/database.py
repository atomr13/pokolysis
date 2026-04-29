import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "football_analyst.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER,
                competition TEXT,
                home_team TEXT,
                away_team TEXT,
                match_date TEXT,
                data_home_win REAL,
                data_draw REAL,
                data_away_win REAL,
                human_home_win REAL,
                human_draw REAL,
                human_away_win REAL,
                user_notes TEXT,
                key_battleground TEXT,
                what_to_watch TEXT,
                upset_condition TEXT,
                ai_summary TEXT,
                user_id INTEGER REFERENCES users(id),
                analysis_score REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id INTEGER REFERENCES predictions(id),
                actual_home_score INTEGER,
                actual_away_score INTEGER,
                actual_outcome TEXT,
                data_correct INTEGER,
                human_correct INTEGER,
                logged_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # Migrate existing DBs that predate user_id / analysis_score columns
    _migrate(conn)

    # Seed the sole user
    _seed_users()


def _migrate(conn):
    """Add new columns to an existing DB without dropping data."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(predictions)").fetchall()
    }
    if "user_id" not in existing:
        conn.execute("ALTER TABLE predictions ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if "analysis_score" not in existing:
        conn.execute("ALTER TABLE predictions ADD COLUMN analysis_score REAL")
    conn.commit()


def _seed_users():
    """Seed the default user (id=1). Update nickname via the DB after first run."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, nickname) VALUES (1, 'analyst')"
        )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_stats(user_id: int) -> dict:
    """Returns commented match count and average analysis score for a user."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS commented_matches,
                ROUND(AVG(analysis_score), 2) AS avg_score
            FROM predictions
            WHERE user_id = ? AND user_notes IS NOT NULL AND user_notes != ''
        """, (user_id,)).fetchone()
        d = dict(row)
    return {
        "commented_matches": d["commented_matches"] or 0,
        "avg_score":         d["avg_score"],  # None until first graded match
    }


def update_analysis_score(prediction_id: int, score: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE predictions SET analysis_score = ? WHERE id = ?",
            (score, prediction_id),
        )


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

def save_prediction(data: dict) -> int:
    """Insert a prediction row. Returns the new row id."""
    sql = """
        INSERT INTO predictions (
            match_id, competition, home_team, away_team, match_date,
            data_home_win, data_draw, data_away_win,
            human_home_win, human_draw, human_away_win,
            user_notes, key_battleground, what_to_watch, upset_condition, ai_summary,
            user_id
        ) VALUES (
            :match_id, :competition, :home_team, :away_team, :match_date,
            :data_home_win, :data_draw, :data_away_win,
            :human_home_win, :human_draw, :human_away_win,
            :user_notes, :key_battleground, :what_to_watch, :upset_condition, :ai_summary,
            :user_id
        )
    """
    with get_conn() as conn:
        cur = conn.execute(sql, data)
        return cur.lastrowid


def get_prediction(prediction_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
        ).fetchone()
        return dict(row) if row else None


def get_pending_predictions() -> list[dict]:
    """Returns predictions that don't have a result logged yet."""
    sql = """
        SELECT p.* FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        WHERE r.id IS NULL
        ORDER BY p.created_at ASC
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]


def get_prediction_by_match_id(match_id: int) -> dict | None:
    """Returns the most recent saved prediction for a given match."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM predictions WHERE match_id = ? ORDER BY created_at DESC LIMIT 1",
            (match_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_predictions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM predictions ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def save_result(prediction_id: int, home_score: int, away_score: int) -> int:
    pred = get_prediction(prediction_id)
    if not pred:
        raise ValueError(f"No prediction found with id={prediction_id}")

    if home_score > away_score:
        actual_outcome = "home_win"
    elif away_score > home_score:
        actual_outcome = "away_win"
    else:
        actual_outcome = "draw"

    data_probs = {
        "home_win": pred["data_home_win"],
        "draw":     pred["data_draw"],
        "away_win": pred["data_away_win"],
    }
    data_pick = max(data_probs, key=data_probs.get)
    data_correct = 1 if data_pick == actual_outcome else 0

    human_probs = {
        "home_win": pred["human_home_win"],
        "draw":     pred["human_draw"],
        "away_win": pred["human_away_win"],
    }
    human_pick = max(human_probs, key=human_probs.get)
    human_correct = 1 if human_pick == actual_outcome else 0

    sql = """
        INSERT INTO results (
            prediction_id, actual_home_score, actual_away_score,
            actual_outcome, data_correct, human_correct
        ) VALUES (?, ?, ?, ?, ?, ?)
    """
    with get_conn() as conn:
        cur = conn.execute(sql, (
            prediction_id, home_score, away_score,
            actual_outcome, data_correct, human_correct
        ))
        return cur.lastrowid


def get_history() -> list[dict]:
    sql = """
        SELECT
            p.*,
            r.actual_home_score,
            r.actual_away_score,
            r.actual_outcome,
            r.data_correct,
            r.human_correct,
            r.logged_at AS result_logged_at
        FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        ORDER BY p.created_at DESC
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]


def get_accuracy_stats() -> dict:
    sql = """
        SELECT
            COUNT(*) AS total_predictions,
            SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END) AS logged,
            SUM(r.data_correct) AS data_correct_count,
            SUM(r.human_correct) AS human_correct_count
        FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
    """
    with get_conn() as conn:
        row = conn.execute(sql).fetchone()
        d = dict(row)

    logged = d["logged"] or 0
    return {
        "total_predictions": d["total_predictions"],
        "logged":            logged,
        "pending":           d["total_predictions"] - logged,
        "data_accuracy":     round(d["data_correct_count"] / logged * 100, 1) if logged else None,
        "human_accuracy":    round(d["human_correct_count"] / logged * 100, 1) if logged else None,
    }


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print(f"DB initialised at {DB_PATH}")
    user = get_user(1)
    print(f"User: {user}")
    stats = get_user_stats(1)
    print(f"User stats: {stats}")
