"""Preview the app without Yahoo: real 2026 field goals, made-up managers and lineups.

    DATA_DIR=./demo-data python -m scripts.demo
    DATA_DIR=./demo-data SCHEDULER=off flask --app app.web run

Everything except the Yahoo sign-in runs for real, including the nflverse downloads.
"""
import random

from app import config, nflverse, refresh, yahoo
from tests.fake_yahoo import FakeYahoo

MANAGERS = ["Joanna", "Jen", "Mike", "Stephen", "Alicia", "Dana", "Priya", "Marcus", "Theo",
            "Renee", "Caleb", "Yuki", "Omar", "Beth"]
TEAM_NAMES = ["Sample Team %d" % i for i in range(1, 15)]


def main():
    fgs, _, max_week = nflverse.load_field_goals(2026, 17)
    seen = {}
    for fg in fgs:
        seen[fg["gsis_id"]] = fg["team"]
    kickers = []
    for row in nflverse.load_id_rows():
        if row["gsis_id"] in seen and row["position"] == "PK":
            yid = row["yahoo_id"] if row["yahoo_id"] != "NA" else row["stats_id"]
            team = {"LA": "LAR"}.get(seen[row["gsis_id"]], seen[row["gsis_id"]])
            kickers.append({"yahoo_id": yid, "name": row["name"], "team": team.title()
                            if len(team) == 3 and team not in ("LAR", "LAC", "NYG", "NYJ") else team,
                            "bye": 11})
    rng = random.Random(7)
    rng.shuffle(kickers)
    main_kicker = {i + 1: kickers[i] for i in range(14)}
    spare = kickers[14:]

    def lineup(team_id, week):
        if team_id == 9 and week == 3:
            return None, [main_kicker[team_id]]            # forgot to start a kicker
        if (team_id + week) % 6 == 0:
            return rng.choice(spare), [main_kicker[team_id]]   # streamed a different kicker
        return main_kicker[team_id], []

    teams = [{"id": i + 1, "name": TEAM_NAMES[i], "nickname": MANAGERS[i]} for i in range(14)]
    fake = FakeYahoo(config.LEAGUE_ID, teams, lineup, current_week=max_week + 1)
    yahoo.get = fake.get
    result = refresh.run()
    print("\n".join(result["log"]))


if __name__ == "__main__":
    main()
