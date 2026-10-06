"""Turn the stored data into the two tables on the page."""
import json
import re

from . import config, db
from .nflverse import nfl_team


def build():
    league = db.get("league")
    if not league:
        return None
    with db.connect() as con:
        teams = [dict(r) for r in con.execute("SELECT * FROM teams ORDER BY team_id")]
        starts = {(r["week"], r["team_key"]): r for r in con.execute("SELECT * FROM starts")}
        best = {(r["week"], r["gsis_id"]): r["d"] for r in con.execute(
            "SELECT week, gsis_id, MAX(distance) AS d FROM fgs GROUP BY week, gsis_id")}
        played = {(r["week"], r["team"]) for r in con.execute("SELECT * FROM played")}
        ids = {r["yahoo_id"]: r["gsis_id"] for r in con.execute("SELECT * FROM kicker_ids")}

    weeks = range(league["start_week"], league["last_week"] + 1)
    playoff_start = league.get("playoff_start_week")
    managers = []
    for team in teams:
        rows = [_week(w, starts.get((w, team["team_key"])), best, played, ids, league)
                for w in weeks]
        for r in rows:
            r["playoffs"] = bool(playoff_start and r["week"] >= playoff_start)
        top = max((r for r in rows if r["longest"]), key=lambda r: (r["longest"], -r["week"]),
                  default=None)
        managers.append({
            "id": team["team_key"], "team": team["name"], "manager": team["manager"],
            "weeks": rows,
            "longest": top["longest"] if top else None,
            "week": top["week"] if top else None,
            "kicker": top["kicker"] if top else None,
        })

    out = out_of_bet(teams)
    for m in managers:
        m["in_bet"] = m["id"] not in out

    # Everyone is listed longest-first, but only managers in the bet get a rank.
    managers.sort(key=lambda m: (-(m["longest"] or 0), (m["team"] or "").lower()))
    place, prev = 0, None
    for m in managers:
        m["rank"] = None
        if not m["in_bet"] or m["longest"] is None:
            continue
        place += 1
        if prev and prev["longest"] == m["longest"]:
            m["rank"] = prev["rank"]  # ties share a rank
        else:
            m["rank"] = place
        prev = m
    return {
        "league": league["name"], "season": league["season"],
        "first_week": league["start_week"], "last_week": league["last_week"],
        "playoff_start_week": playoff_start,
        "current_week": league["current_week"],
        "updated": db.get("last_success"),
        "managers": managers,
    }


def out_of_bet(teams):
    """Team keys of managers who are not in the bet.

    The admin page's checkboxes win once they have been saved. Until then, managers are
    matched by first name against the NOT_IN_BET list.
    """
    saved = db.get("out_of_bet")
    if saved is not None:
        return set(saved)
    out = set()
    for team in teams:
        words = set(re.findall(r"[a-z]+", (team["manager"] or "").lower()))
        if words & set(config.NOT_IN_BET):
            out.add(team["team_key"])
    return out


def _week(week, start, best, played, ids, league):
    row = {"week": week, "kicker": None, "longest": None}
    if start is None:
        row["status"] = "upcoming" if week >= league["current_week"] else "missing"
        return row
    kickers = json.loads(start["kickers"])
    if not kickers:
        row["status"] = "no_kicker"
        return row
    results = [_kicker(week, k, best, played, ids) for k in kickers]
    # A league has one K slot; if there were ever two, the longer kick counts.
    top = max(results, key=lambda r: r["longest"] or 0)
    row.update(top)
    return row


def _kicker(week, k, best, played, ids):
    label = f"{k['name']} ({k['nfl_team']})" if k.get("nfl_team") else k["name"]
    gsis = ids.get(k["yahoo_id"])
    distance = best.get((week, gsis)) if gsis else None
    if distance:
        status = "made"
    elif not gsis:
        status = "unmatched"
    elif k.get("bye_week") == week:
        status = "bye"
    elif (week, nfl_team(k.get("nfl_team"))) in played:
        status = "no_fg"
    else:
        status = "pending"
    return {"kicker": label, "longest": distance, "status": status}
