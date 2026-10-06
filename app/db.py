"""Small SQLite store: Yahoo tokens, league info, weekly kicker starts, field goals."""
import json
import os
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teams (
    team_key TEXT PRIMARY KEY, team_id INTEGER, name TEXT, manager TEXT);
CREATE TABLE IF NOT EXISTS starts (
    week INTEGER, team_key TEXT, kickers TEXT NOT NULL, final INTEGER NOT NULL,
    PRIMARY KEY (week, team_key));
CREATE TABLE IF NOT EXISTS fgs (
    week INTEGER, gsis_id TEXT, distance INTEGER, kicker TEXT, team TEXT);
CREATE TABLE IF NOT EXISTS played (week INTEGER, team TEXT, PRIMARY KEY (week, team));
CREATE TABLE IF NOT EXISTS kicker_ids (
    yahoo_id TEXT PRIMARY KEY, gsis_id TEXT, name TEXT, how TEXT);
"""


def path():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, "kicker.db")


@contextmanager
def connect():
    con = sqlite3.connect(path(), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def get(key, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put(key, value):
    with connect() as con:
        con.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
