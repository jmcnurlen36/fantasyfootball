"""Field goal distances from nflverse play-by-play, plus the Yahoo-to-NFL player ID map."""
import csv
import gzip
import io
import os
import re
import tempfile

import requests

PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{season}.csv.gz")
IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
TIMEOUT = 120

# Yahoo and nflverse agree on every team abbreviation except the Rams.
YAHOO_TEAM_FIXES = {"LAR": "LA"}


def nfl_team(yahoo_abbr):
    abbr = (yahoo_abbr or "").upper()
    return YAHOO_TEAM_FIXES.get(abbr, abbr)


def _download(url):
    r = requests.get(url, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    fd, tmp = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    return tmp


def read_field_goals(lines, last_week):
    """Return (made field goals, teams that played each week, latest week in the data).

    Only regular-season weeks up to last_week count. Missed and blocked kicks are dropped.
    """
    reader = csv.reader(lines)
    col = {name: i for i, name in enumerate(next(reader))}
    fgs, played, max_week = [], set(), 0
    for row in reader:
        if row[col["season_type"]] != "REG":
            continue
        week = int(row[col["week"]])
        if week > last_week:
            continue
        max_week = max(max_week, week)
        played.add((week, row[col["home_team"]]))
        played.add((week, row[col["away_team"]]))
        if row[col["field_goal_result"]] != "made":
            continue
        distance = row[col["kick_distance"]]
        if distance in ("", "NA"):
            continue
        fgs.append({
            "week": week,
            "gsis_id": row[col["kicker_player_id"]],
            "distance": int(float(distance)),
            "kicker": row[col["kicker_player_name"]],
            "team": row[col["posteam"]],
        })
    return fgs, played, max_week


def load_field_goals(season, last_week):
    tmp = _download(PBP_URL.format(season=season))
    try:
        with gzip.open(tmp, "rt", encoding="utf-8", newline="") as f:
            return read_field_goals(f, last_week)
    finally:
        os.unlink(tmp)


def load_id_rows():
    r = requests.get(IDS_URL, timeout=TIMEOUT)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8"))))


def _has(value):
    return value not in (None, "", "NA")


def normalize_name(name):
    name = re.sub(r"[^a-z ]", "", (name or "").lower())
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    return " ".join(name.split())


class KickerMatcher:
    """Find the NFL (gsis) ID for a Yahoo kicker. Never guesses: no match returns None."""

    def __init__(self, id_rows):
        self.by_yahoo, by_stats, by_name = {}, {}, {}
        for row in id_rows:
            if not _has(row.get("gsis_id")):
                continue
            if _has(row.get("yahoo_id")):
                self.by_yahoo[row["yahoo_id"]] = row["gsis_id"]
            if row.get("position") == "PK":
                if _has(row.get("stats_id")) and not _has(row.get("yahoo_id")):
                    by_stats.setdefault(row["stats_id"], set()).add(row["gsis_id"])
                by_name.setdefault(row.get("merge_name") or normalize_name(row.get("name")),
                                   set()).add(row["gsis_id"])
        # Only keep fallbacks that point at exactly one player.
        self.by_stats = {k: next(iter(v)) for k, v in by_stats.items() if len(v) == 1}
        self.by_name = {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1}

    def match(self, yahoo_id, name):
        if yahoo_id in self.by_yahoo:
            return self.by_yahoo[yahoo_id], "yahoo id"
        # Newer players often have no Yahoo ID listed, but their "stats" ID is the same number.
        if yahoo_id in self.by_stats:
            return self.by_stats[yahoo_id], "stats id"
        key = normalize_name(name)
        if key in self.by_name:
            return self.by_name[key], "name"
        return None, "unmatched"
