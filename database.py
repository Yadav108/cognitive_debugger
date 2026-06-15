import aiosqlite
from datetime import datetime

from config import DB_PATH


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                problem_text TEXT NOT NULL,
                problem_image_path TEXT,
                concept_graph_json TEXT NOT NULL,
                domain TEXT NOT NULL,
                current_turn INTEGER DEFAULT 0,
                max_turns INTEGER DEFAULT 3,
                resolved INTEGER DEFAULT 0,
                final_root_cause TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS iterations (
                iteration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                parsed_steps_json TEXT,
                coverage_matrix_json TEXT,
                missing_nodes_json TEXT,
                root_divergence_json TEXT,
                inter_node_failures_json TEXT,
                confidence REAL,
                iteration_complete INTEGER,
                feedback TEXT,
                probe_question TEXT,
                teaching_json TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                iteration_id INTEGER,
                call_name TEXT NOT NULL,
                input_json TEXT,
                raw_output TEXT,
                parsed_output_json TEXT,
                valid INTEGER,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS backtracking_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iteration_id INTEGER NOT NULL,
                trace_json TEXT NOT NULL,
                FOREIGN KEY(iteration_id) REFERENCES iterations(iteration_id)
            )
        """)

        # No migration tooling exists yet — add new columns to existing DBs here.
        await _ensure_column(db, "iterations", "teaching_json", "TEXT")

        await db.commit()


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, col_type: str):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in await cursor.fetchall()]
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


async def insert_session(session_data: dict):
    columns = ", ".join(session_data.keys())
    placeholders = ", ".join("?" * len(session_data))
    values = tuple(session_data.values())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO sessions ({columns}) VALUES ({placeholders})",
            values,
        )
        await db.commit()


async def get_session(session_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_session(session_id: str, updates: dict):
    payload = {**updates, "updated_at": _now()}
    set_clause = ", ".join(f"{col} = ?" for col in payload)
    values = (*payload.values(), session_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"UPDATE sessions SET {set_clause} WHERE session_id = ?",
            values,
        )
        await db.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"Session '{session_id}' not found")


async def insert_iteration(iteration_data: dict) -> int:
    columns = ", ".join(iteration_data.keys())
    placeholders = ", ".join("?" * len(iteration_data))
    values = tuple(iteration_data.values())
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"INSERT INTO iterations ({columns}) VALUES ({placeholders})",
            values,
        )
        await db.commit()
        return cursor.lastrowid


async def insert_llm_call(call_data: dict):
    columns = ", ".join(call_data.keys())
    placeholders = ", ".join("?" * len(call_data))
    values = tuple(call_data.values())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO llm_calls ({columns}) VALUES ({placeholders})",
            values,
        )
        await db.commit()


async def insert_backtracking_trace(iteration_id: int, trace_json: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO backtracking_traces (iteration_id, trace_json) VALUES (?, ?)",
            (iteration_id, trace_json),
        )
        await db.commit()


async def get_iterations(session_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM iterations WHERE session_id = ? ORDER BY turn_index ASC",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
