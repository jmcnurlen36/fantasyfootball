"""The web app: the public report page, an admin page, and the background refresh."""
import hmac
import threading
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from . import config, db, refresh, report, yahoo

app = Flask(__name__)


def admin_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not config.ADMIN_PASSWORD:
            return Response("Set the ADMIN_PASSWORD secret to use the admin page.", 503)
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.password or "", config.ADMIN_PASSWORD):
            return Response("Sign in required.", 401,
                            {"WWW-Authenticate": 'Basic realm="Kicker Bet admin"'})
        return view(*args, **kwargs)
    return wrapped


@app.get("/")
def index():
    return render_template("index.html", report=report.build())


@app.get("/api/report")
def api_report():
    return jsonify(report.build())


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/admin")
@admin_only
def admin():
    return render_template(
        "admin.html",
        connected=yahoo.is_connected(),
        has_keys=bool(config.CLIENT_ID and config.CLIENT_SECRET),
        authorize_url=yahoo.authorize_url(),
        redirect_uri=config.REDIRECT_URI,
        last=db.get("last_refresh"),
        running=refresh.is_running(),
        unmatched=db.get("unmatched") or [],
        message=request.args.get("message", ""),
        hours=config.REFRESH_HOURS,
        teams=_teams_with_bet(),
    )


def _teams_with_bet():
    with db.connect() as con:
        teams = [dict(r) for r in con.execute("SELECT * FROM teams ORDER BY name")]
    out = report.out_of_bet(teams)
    for team in teams:
        team["in_bet"] = team["team_key"] not in out
    return teams


@app.post("/admin/bet")
@admin_only
def admin_bet():
    in_bet = set(request.form.getlist("in_bet"))
    with db.connect() as con:
        keys = [r["team_key"] for r in con.execute("SELECT team_key FROM teams")]
    db.put("out_of_bet", [k for k in keys if k not in in_bet])
    return redirect(url_for("admin", message="Saved who is in the bet."))


@app.post("/admin/connect")
@admin_only
def admin_connect():
    code = yahoo.code_from_paste(request.form.get("code", ""))
    if not code:
        return redirect(url_for("admin", message="Paste the address or code from Yahoo first."))
    try:
        yahoo.exchange_code(code)
    except Exception as exc:
        return redirect(url_for("admin", message=str(exc)))
    threading.Thread(target=refresh.run, daemon=True).start()
    return redirect(url_for("admin", message="Yahoo connected. First refresh started."))


@app.post("/admin/refresh")
@admin_only
def admin_refresh():
    if not yahoo.is_connected():
        return redirect(url_for("admin", message="Connect Yahoo before refreshing."))
    threading.Thread(target=refresh.run, daemon=True).start()
    return redirect(url_for("admin", message="Refresh started. Reload in about a minute."))


def _scheduler():
    """Refresh every REFRESH_HOURS while the app is running."""
    while True:
        time.sleep(60)
        try:
            if not yahoo.is_connected() or refresh.is_running():
                continue
            last = db.get("last_refresh")
            age = (time.time() - datetime.fromisoformat(last["at"]).timestamp()
                   if last else float("inf"))
            if age >= config.REFRESH_HOURS * 3600:
                refresh.run()
        except Exception as exc:
            print(f"scheduler error: {exc}", flush=True)


if config.SCHEDULER:
    threading.Thread(target=_scheduler, daemon=True).start()
