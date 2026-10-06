import json

import pytest

from app import config, db, nflverse, refresh, report, yahoo
from tests.fake_yahoo import FakeYahoo

AUBREY = {"yahoo_id": "40000", "name": "Brandon Aubrey", "team": "Dal", "bye": 10}
LOOP = {"yahoo_id": "41988", "name": "Tyler Loop", "team": "Bal", "bye": 7}      # stats id only
BASS = {"yahoo_id": "32858", "name": "Tyler Bass", "team": "Buf", "bye": 2}
NOBODY = {"yahoo_id": "77777", "name": "Mystery Kicker", "team": "LAR", "bye": 8}
QB = {"yahoo_id": "5228", "name": "Some Quarterback", "team": "NE", "pos": "QB"}

ID_ROWS = [
    {"gsis_id": "00-A", "yahoo_id": "40000", "stats_id": "40000", "position": "PK",
     "name": "Brandon Aubrey", "merge_name": "brandon aubrey"},
    {"gsis_id": "00-L", "yahoo_id": "NA", "stats_id": "41988", "position": "PK",
     "name": "Tyler Loop", "merge_name": "tyler loop"},
    {"gsis_id": "00-B", "yahoo_id": "32858", "stats_id": "32858", "position": "PK",
     "name": "Tyler Bass", "merge_name": "tyler bass"},
    {"gsis_id": "NA", "yahoo_id": "1", "stats_id": "1", "position": "PK", "name": "X", "merge_name": "x"},
]

HEADER = ("season_type,week,home_team,away_team,posteam,field_goal_result,kick_distance,"
          "kicker_player_name,kicker_player_id")
PBP = [
    HEADER,
    "REG,1,DAL,PHI,DAL,made,52,B.Aubrey,00-A",
    "REG,1,DAL,PHI,DAL,made,61,B.Aubrey,00-A",
    "REG,1,DAL,PHI,DAL,missed,66,B.Aubrey,00-A",       # misses never count
    "REG,1,BAL,BUF,BAL,blocked,58,T.Loop,00-L",
    "REG,1,BAL,BUF,BUF,,NA,,",
    "REG,2,BAL,CLE,BAL,made,64,T.Loop,00-L",
    "REG,2,DAL,NYG,DAL,made,61,B.Aubrey,00-A",
    "REG,15,DAL,WAS,DAL,made,70,B.Aubrey,00-A",        # playoffs: ignored
    "POST,1,DAL,WAS,DAL,made,71,B.Aubrey,00-A",
]

TEAMS = [
    {"id": 1, "name": "Golden", "nickname": "Joanna"},
    {"id": 2, "name": "Leg Day", "nickname": "Mike"},        # not in the bet
    {"id": 3, "name": "Wide Left", "nickname": "--hidden--"},
    {"id": 4, "name": "No Kicker FC", "nickname": "Sam"},
]


def lineup(team_id, week):
    if team_id == 1:
        return AUBREY, [QB]
    if team_id == 2:
        return LOOP, [AUBREY]          # Aubrey on the bench must not count for team 2
    if team_id == 3:
        return (BASS if week == 1 else NOBODY), []
    return None, [BASS]


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    fake = FakeYahoo(config.LEAGUE_ID, TEAMS, lineup, current_week=3)
    monkeypatch.setattr(yahoo, "get", fake.get)
    monkeypatch.setattr(nflverse, "load_field_goals",
                        lambda season, last_week: nflverse.read_field_goals(iter(PBP), last_week))
    monkeypatch.setattr(nflverse, "load_id_rows", lambda: ID_ROWS)
    return fake


def by_team(rep):
    return {m["team"]: m for m in rep["managers"]}


def test_refresh_and_report(app_data):
    result = refresh.run()
    assert result["ok"], result["log"]
    rep = report.build()
    assert (rep["first_week"], rep["last_week"]) == (1, 14)      # playoffs start week 15
    teams = by_team(rep)

    golden = teams["Golden"]
    assert (golden["longest"], golden["week"], golden["kicker"]) == (61, 1, "Brandon Aubrey (DAL)")
    assert golden["weeks"][1]["longest"] == 61
    assert golden["weeks"][2]["status"] == "pending"             # week 3 has no games yet
    assert golden["weeks"][3]["status"] == "upcoming"
    assert len(golden["weeks"]) == 14

    leg = teams["Leg Day"]                                       # matched through the stats id
    assert (leg["longest"], leg["week"]) == (64, 2)
    assert leg["weeks"][0]["status"] == "no_fg"                  # blocked kick only

    wide = teams["Wide Left"]
    assert wide["manager"] == "" and wide["longest"] is None
    assert wide["weeks"][0]["status"] == "no_fg"                 # Bass played, made nothing
    assert wide["weeks"][1]["status"] == "unmatched"
    assert teams["No Kicker FC"]["weeks"][0]["status"] == "no_kicker"
    assert db.get("unmatched") == ["Mystery Kicker"]


def test_bet_membership_and_ranks(app_data):
    refresh.run()
    teams = by_team(report.build())
    assert teams["Leg Day"]["in_bet"] is False and teams["Leg Day"]["rank"] is None
    assert teams["Golden"]["rank"] == 1                          # 64 is longer but not in the bet
    assert teams["Wide Left"]["rank"] is None                    # no field goal yet

    order = [m["team"] for m in report.build()["managers"]]
    assert order[:2] == ["Leg Day", "Golden"]                    # still listed longest first

    db.put("out_of_bet", [])                                     # admin override: everyone in
    teams = by_team(report.build())
    assert (teams["Leg Day"]["rank"], teams["Golden"]["rank"]) == (1, 2)


def test_ties_share_a_rank(app_data, monkeypatch):
    tied = PBP + ["REG,2,BAL,CLE,BAL,made,61,T.Loop,00-L"]
    tied.remove("REG,2,BAL,CLE,BAL,made,64,T.Loop,00-L")
    monkeypatch.setattr(nflverse, "load_field_goals",
                        lambda season, last_week: nflverse.read_field_goals(iter(tied), last_week))
    db.put("out_of_bet", [])
    refresh.run()
    teams = by_team(report.build())
    assert teams["Golden"]["rank"] == teams["Leg Day"]["rank"] == 1


def test_finished_weeks_are_fetched_once(app_data):
    refresh.run()
    first = len([c for c in app_data.calls if "roster" in c])
    assert first == 4 * 3                                        # 4 teams, weeks 1 to 3
    app_data.calls.clear()
    refresh.run()
    again = [c for c in app_data.calls if "roster" in c]
    assert len(again) == 4 and all(c.endswith("week=3") for c in again)


def test_bye_week(app_data):
    refresh.run()
    with db.connect() as con:
        row = con.execute("SELECT kickers FROM starts WHERE week=2 AND team_key LIKE '%.t.3'").fetchone()
        kickers = json.loads(row["kickers"])
        kickers[0].update(yahoo_id="32858", bye_week=2)
        con.execute("UPDATE starts SET kickers=? WHERE week=2 AND team_key LIKE '%.t.3'",
                    (json.dumps(kickers),))
    assert by_team(report.build())["Wide Left"]["weeks"][1]["status"] == "bye"


def test_code_from_paste():
    assert yahoo.code_from_paste(" abc123 ") == "abc123"
    assert yahoo.code_from_paste("https://localhost:8080/?code=xyz9&state=") == "xyz9"


def test_sign_in_asks_for_fantasy_scope(monkeypatch):
    monkeypatch.setattr(config, "CLIENT_ID", "new-app")
    assert "scope=fspt-r" in yahoo.authorize_url()


def test_sign_in_from_other_yahoo_app_is_not_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CLIENT_ID", "new-app")
    db.put("yahoo_tokens", {"access_token": "a", "refresh_token": "r", "expires_at": 9e9})
    assert not yahoo.is_connected()                  # saved before tokens recorded their app
    db.put("yahoo_tokens", {"access_token": "a", "refresh_token": "r", "expires_at": 9e9,
                            "client_id": "old-app"})
    assert not yahoo.is_connected()
    with pytest.raises(yahoo.YahooError, match="current Yahoo keys"):
        yahoo.get("game/nfl")
    db.put("yahoo_tokens", {"access_token": "a", "refresh_token": "r", "expires_at": 9e9,
                            "client_id": "new-app"})
    assert yahoo.is_connected()


def test_name_matching_is_exact_and_unambiguous():
    rows = ID_ROWS + [{"gsis_id": "00-Z", "yahoo_id": "NA", "stats_id": "NA", "position": "PK",
                       "name": "Tyler Bass", "merge_name": "tyler bass"}]
    m = nflverse.KickerMatcher(rows)
    assert m.match("999", "Tyler Loop Jr.") == ("00-L", "name")
    assert m.match("999", "Tyler Bass") == (None, "unmatched")   # two players share the name


def test_pages_render(app_data):
    from app.web import app
    client = app.test_client()
    assert b"No data yet" in client.get("/").data
    refresh.run()
    page = client.get("/").data
    assert b"Longest field goal by manager" in page and b"Brandon Aubrey" in page
    assert client.get("/admin").status_code == 503               # no admin password set
    config.ADMIN_PASSWORD = "pw"
    try:
        assert client.get("/admin").status_code == 401
        ok = client.get("/admin", auth=("admin", "pw"))
        assert ok.status_code == 200 and b"Who is in the bet" in ok.data
        keys = [t["team_key"] for t in __import__("app.web", fromlist=["x"])._teams_with_bet()]
        client.post("/admin/bet", data={"in_bet": keys[:1]}, auth=("admin", "pw"))
        assert len(db.get("out_of_bet")) == 3
    finally:
        config.ADMIN_PASSWORD = ""
