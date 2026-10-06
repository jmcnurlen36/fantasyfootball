# Kicker Bet

One page for the league's kicker bet:

1. **Longest field goal by manager** for the regular season, with the kicker and week.
2. **Week by week** for any manager: the kicker they started and that kicker's longest field goal.

Lineups come from Yahoo (read-only). Distances come from nflverse play-by-play.

## Rules the app applies

- Regular season only. The app stops the week before Yahoo says playoffs start (week 14 for this league).
- The kicker in the K slot counts. Kickers on the bench do not.
- Made field goals only. Misses and blocks are ignored.
- Managers not in the bet stay on the page greyed out, and are not ranked.
- Ties share a rank.

## Deploy to Fly

Run these from this folder. Yahoo keys go into Fly secrets and never into a file.

```
fly launch --no-deploy --copy-config --name kicker-bet --region ewr
fly volumes create kicker_data --region ewr --size 1
fly secrets set YAHOO_CLIENT_ID="paste client id" YAHOO_CLIENT_SECRET="paste client secret" ADMIN_PASSWORD="choose a password"
fly deploy --ha=false
```

If the name `kicker-bet` is taken, pick another and use it in place of `kicker-bet` below.

## Connect Yahoo (once)

1. Open `https://kicker-bet.fly.dev/admin`. Username can be anything; the password is your `ADMIN_PASSWORD`.
2. Click **Open Yahoo and click Agree**.
3. Yahoo sends the browser to `https://localhost:8080/?code=...`, which shows a connection error. That is expected.
4. Copy that whole address, paste it into the admin page, and click **Connect Yahoo**.

The first refresh starts right away and takes about a minute. After that it runs every 6 hours, and
**Refresh now** on the admin page runs it on demand.

## Who is in the bet

The app starts by greying out managers whose Yahoo nickname contains Jen, Mike, Stephen or Alicia.
Yahoo nicknames can be hidden or spelled differently, so check the **Who is in the bet** list on
the admin page after the first refresh and fix any ticks there. Saved ticks override the name list.

## Preview without Yahoo

```
pip install -r requirements.txt pytest
DATA_DIR=./demo-data python -m scripts.demo
DATA_DIR=./demo-data SCHEDULER=off flask --app app.web run
```

This uses real 2026 field goals with made-up managers and lineups. `python -m pytest tests` runs the tests.

## If something looks wrong

The admin page shows the log of the last refresh, including any error from Yahoo and any kicker
that could not be matched to NFL data. `fly logs` has the full detail.

## Settings (environment variables)

| Name | Default | What it does |
|---|---|---|
| `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET` | none | From the Yahoo developer app |
| `ADMIN_PASSWORD` | none | Protects `/admin` |
| `YAHOO_LEAGUE_ID` | 746192 | The league |
| `YAHOO_REDIRECT_URI` | https://localhost:8080 | Must match the Yahoo app exactly |
| `REFRESH_HOURS` | 6 | Hours between automatic refreshes |
| `NOT_IN_BET` | Jen,Mike,Stephen,Alicia | Starting list of managers to grey out |
| `LAST_REGULAR_SEASON_WEEK` | 14 | Used only if Yahoo does not report the playoff start |
