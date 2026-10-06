"""A stand-in for Yahoo that answers the app's four calls with XML in Yahoo's format.

Used by the tests and by scripts/demo.py so the app can run end to end without a Yahoo sign-in.
"""
from xml.sax.saxutils import escape

from app import yahoo

NS = ('xmlns:yahoo="http://www.yahooapis.com/v1/base.rng" '
      'xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng"')
HEAD = f'<?xml version="1.0" encoding="UTF-8"?>\n<fantasy_content xml:lang="en-US" {NS}>'
GAME_KEY, SEASON = "999", 2026


def _player(p, position, week):
    return f"""<player><player_key>{GAME_KEY}.p.{p['yahoo_id']}</player_key>
      <player_id>{p['yahoo_id']}</player_id>
      <name><full>{escape(p['name'])}</full></name>
      <editorial_team_abbr>{p['team']}</editorial_team_abbr>
      <bye_weeks><week>{p.get('bye', 9)}</week></bye_weeks>
      <display_position>{p.get('pos', 'K')}</display_position>
      <selected_position><coverage_type>week</coverage_type><week>{week}</week>
        <position>{position}</position></selected_position></player>"""


class FakeYahoo:
    """teams: [{'id', 'name', 'nickname'}]; lineup(team_id, week) -> (starter or None, bench)."""

    def __init__(self, league_id, teams, lineup, current_week=5, playoff_start_week=15):
        self.league_key = f"{GAME_KEY}.l.{league_id}"
        self.teams, self.lineup = teams, lineup
        self.current_week, self.playoff_start_week = current_week, playoff_start_week
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return yahoo.parse_xml(self.xml(path))

    def xml(self, path):
        if path == "game/nfl":
            body = f"<game><game_key>{GAME_KEY}</game_key><code>nfl</code><season>{SEASON}</season></game>"
        elif path == f"league/{self.league_key}/settings":
            body = f"""<league><league_key>{self.league_key}</league_key>
              <name>Demo League</name><current_week>{self.current_week}</current_week>
              <start_week>1</start_week><end_week>17</end_week><is_finished>0</is_finished>
              <settings><uses_playoff>1</uses_playoff>
                <playoff_start_week>{self.playoff_start_week}</playoff_start_week></settings></league>"""
        elif path == f"league/{self.league_key}/teams":
            teams = "".join(f"""<team><team_key>{self.league_key}.t.{t['id']}</team_key>
              <team_id>{t['id']}</team_id><name>{escape(t['name'])}</name>
              <managers><manager><manager_id>{t['id']}</manager_id>
                <nickname>{escape(t['nickname'])}</nickname></manager></managers></team>"""
                            for t in self.teams)
            body = f"<league><league_key>{self.league_key}</league_key><teams>{teams}</teams></league>"
        elif path.startswith("team/") and "/roster;week=" in path:
            team_key, week = path[5:].split("/roster;week=")
            team_id, week = int(team_key.rsplit(".", 1)[1]), int(week)
            starter, bench = self.lineup(team_id, week)
            players = "".join(_player(p, "BN", week) for p in bench)
            if starter:
                players += _player(starter, "K", week)
            body = f"""<team><team_key>{team_key}</team_key><roster><coverage_type>week</coverage_type>
              <week>{week}</week><players>{players}</players></roster></team>"""
        else:
            raise yahoo.YahooError(f"Yahoo returned 404 for {path}")
        return f"{HEAD}{body}</fantasy_content>"
