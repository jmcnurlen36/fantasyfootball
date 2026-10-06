"""Pull the latest lineups from Yahoo and field goals from nflverse into the database."""
import json
import threading
import traceback
from datetime import datetime, timezone

from . import config, db, nflverse, yahoo

_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_running():
    return _lock.locked()


def run():
    """Run one refresh. Returns the result that is also saved for the admin page."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "log": ["A refresh is already running."]}
    log, ok = [], True
    try:
        for step in (_yahoo, _field_goals, _match_kickers):
            try:
                step(log)
            except Exception as exc:  # keep going: the steps are independent
                ok = False
                log.append(f"FAILED {step.__name__.strip('_')}: {exc}")
                print(traceback.format_exc(), flush=True)
        result = {"at": now(), "ok": ok, "log": log}
        db.put("last_refresh", result)
        if ok:
            db.put("last_success", result["at"])
        return result
    finally:
        _lock.release()


def _yahoo(log):
    game = yahoo.fetch_game()
    league_key = f"{game['game_key']}.l.{config.LEAGUE_ID}"
    league = yahoo.fetch_league(league_key)
    teams = yahoo.fetch_teams(league_key)
    if not teams:
        raise yahoo.YahooError("Yahoo returned no teams for the league.")

    # Regular season only: stop the week before playoffs start.
    last_week = (league["playoff_start_week"] - 1 if league["playoff_start_week"]
                 else config.LAST_WEEK_FALLBACK)
    if league["end_week"]:
        last_week = min(last_week, league["end_week"])
    current = league["current_week"] or league["start_week"]

    with db.connect() as con:
        con.execute("DELETE FROM teams")
        con.executemany(
            "INSERT INTO teams VALUES (:team_key, :team_id, :name, :manager)", teams)
        done = {(r["week"], r["team_key"])
                for r in con.execute("SELECT week, team_key FROM starts WHERE final=1")}
    db.put("league", {
        "name": league["name"], "season": game["season"], "league_key": league_key,
        "start_week": league["start_week"], "last_week": last_week, "current_week": current,
    })

    fetched = 0
    for week in range(league["start_week"], min(current, last_week) + 1):
        final = 1 if (week < current or league["is_finished"]) else 0
        for team in teams:
            if (week, team["team_key"]) in done:
                continue  # finished weeks never change, so they are fetched once
            kickers = yahoo.fetch_started_kickers(team["team_key"], week)
            with db.connect() as con:
                con.execute(
                    "INSERT OR REPLACE INTO starts VALUES (?, ?, ?, ?)",
                    (week, team["team_key"], json.dumps(kickers), final))
            fetched += 1
    log.append(f"Yahoo: {league['name']}, {len(teams)} teams, current week {current}, "
               f"regular season ends week {last_week}, {fetched} lineups fetched.")


def _field_goals(log):
    league = db.get("league")
    if not league:
        raise RuntimeError("No league info yet, so the season is unknown.")
    fgs, played, max_week = nflverse.load_field_goals(league["season"], league["last_week"])
    with db.connect() as con:
        con.execute("DELETE FROM fgs")
        con.executemany(
            "INSERT INTO fgs VALUES (:week, :gsis_id, :distance, :kicker, :team)", fgs)
        con.execute("DELETE FROM played")
        con.executemany("INSERT INTO played VALUES (?, ?)", sorted(played))
    log.append(f"Field goals: {len(fgs)} made kicks through week {max_week}.")


def _match_kickers(log):
    with db.connect() as con:
        rows = con.execute("SELECT kickers FROM starts").fetchall()
    kickers = {k["yahoo_id"]: k["name"] for r in rows for k in json.loads(r["kickers"])}
    if not kickers:
        return
    matcher = nflverse.KickerMatcher(nflverse.load_id_rows())
    matched = [(yid, *matcher.match(yid, name), name) for yid, name in kickers.items()]
    with db.connect() as con:
        con.execute("DELETE FROM kicker_ids")
        con.executemany(
            "INSERT INTO kicker_ids (yahoo_id, gsis_id, how, name) VALUES (?, ?, ?, ?)", matched)
    missing = sorted(name for _, gsis, _, name in matched if not gsis)
    db.put("unmatched", missing)
    log.append(f"Kickers: {len(matched) - len(missing)} of {len(matched)} matched to NFL data."
               + (f" Not matched: {', '.join(missing)}." if missing else ""))
