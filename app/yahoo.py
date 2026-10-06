"""Yahoo Fantasy Sports: OAuth 2.0 sign-in and the four read-only calls this app needs.

Yahoo's API answers in XML. The parse_* functions turn that into plain dicts and are
kept separate from the network code so they can be tested against saved responses.
"""
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from . import config, db

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
TIMEOUT = 30
# Fantasy Sports, read only. Asking for it by name makes Yahoo's consent page show it,
# and makes Yahoo refuse there (not later with a 403) if the developer app lacks it.
SCOPE = "fspt-r"


class YahooError(Exception):
    pass


# ---------- sign-in ----------

def authorize_url():
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": config.CLIENT_ID,
        "redirect_uri": config.REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
    })


def code_from_paste(text):
    """Accept either the bare code or the whole https://localhost:8080/?code=... address."""
    text = text.strip()
    if "code=" in text:
        query = urllib.parse.urlparse(text).query or text.split("?", 1)[-1]
        return urllib.parse.parse_qs(query).get("code", [""])[0]
    return text


def _token_request(data):
    if not (config.CLIENT_ID and config.CLIENT_SECRET):
        raise YahooError("YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET are not set.")
    r = requests.post(
        TOKEN_URL,
        data={**data, "redirect_uri": config.REDIRECT_URI},
        auth=(config.CLIENT_ID, config.CLIENT_SECRET),
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise YahooError(f"Yahoo sign-in failed ({r.status_code}): {r.text[:300]}")
    body = r.json()
    old = db.get("yahoo_tokens") or {}
    tokens = {
        "access_token": body["access_token"],
        # Keep whatever refresh token Yahoo sends back, in case it rotates them.
        "refresh_token": body.get("refresh_token") or old.get("refresh_token"),
        "expires_at": time.time() + int(body.get("expires_in", 3600)) - 120,
        # Tokens only work with the Yahoo app that issued them; see _saved_tokens.
        "client_id": config.CLIENT_ID,
    }
    db.put("yahoo_tokens", tokens)
    return tokens


def exchange_code(code):
    return _token_request({"grant_type": "authorization_code", "code": code})


def _saved_tokens():
    """The saved tokens, or None if there are none or they came from a different Yahoo app.

    After YAHOO_CLIENT_ID changes, the old access token would keep being sent until it
    expired, so a sign-in made under the old keys must not count as connected.
    """
    tokens = db.get("yahoo_tokens") or {}
    if not tokens.get("refresh_token") or tokens.get("client_id") != config.CLIENT_ID:
        return None
    return tokens


def is_connected():
    return _saved_tokens() is not None


def _access_token(force=False):
    tokens = _saved_tokens()
    if not tokens:
        raise YahooError("Yahoo is not connected with the current Yahoo keys. "
                         "Use the admin page to sign in.")
    if force or time.time() >= tokens["expires_at"]:
        tokens = _token_request(
            {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    return tokens["access_token"]


# ---------- API ----------

def get(path):
    """GET one API path and return the XML root with namespaces removed."""
    url = f"{API}/{path}"
    for attempt in (1, 2):
        token = _access_token(force=(attempt == 2))
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        if r.status_code == 401 and attempt == 1:
            continue
        if r.status_code == 403 and "not authorized" in r.text:
            raise YahooError(
                f"Yahoo returned 403 for {path}: this Yahoo app is not allowed to read "
                "Fantasy Sports. In the Yahoo developer app, tick Fantasy Sports > Read, "
                "then connect Yahoo again on this page.")
        if r.status_code != 200:
            raise YahooError(f"Yahoo returned {r.status_code} for {path}: {r.text[:300]}")
        return parse_xml(r.text)


def parse_xml(text):
    root = ET.fromstring(text)
    for el in root.iter():
        el.tag = el.tag.split("}", 1)[-1]
    return root


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_game(root):
    game = root.find(".//game")
    if game is None:
        raise YahooError("Yahoo's game lookup had no game in it.")
    return {"game_key": game.findtext("game_key"), "season": _int(game.findtext("season"))}


def parse_league(root):
    league = root.find(".//league")
    if league is None:
        raise YahooError("Yahoo's league response had no league in it.")
    return {
        "name": league.findtext("name"),
        "current_week": _int(league.findtext("current_week")),
        "start_week": _int(league.findtext("start_week"), 1),
        "end_week": _int(league.findtext("end_week")),
        "is_finished": league.findtext("is_finished") == "1",
        "playoff_start_week": _int(league.findtext("settings/playoff_start_week")),
    }


def parse_teams(root):
    teams = []
    for team in root.iter("team"):
        nicknames = [m.findtext("nickname") for m in team.iter("manager")]
        nicknames = [n for n in nicknames if n and n != "--hidden--"]
        teams.append({
            "team_key": team.findtext("team_key"),
            "team_id": _int(team.findtext("team_id")),
            "name": team.findtext("name"),
            "manager": " & ".join(nicknames),
        })
    return teams


def parse_started_kickers(root):
    """Players sitting in the K slot. Kickers on the bench are ignored."""
    kickers = []
    for player in root.iter("player"):
        if player.findtext("selected_position/position") != "K":
            continue
        kickers.append({
            "yahoo_id": player.findtext("player_id"),
            "name": player.findtext("name/full"),
            "nfl_team": (player.findtext("editorial_team_abbr") or "").upper(),
            "bye_week": _int(player.findtext("bye_weeks/week")),
        })
    return kickers


def fetch_game():
    return parse_game(get("game/nfl"))


def fetch_league(league_key):
    return parse_league(get(f"league/{league_key}/settings"))


def fetch_teams(league_key):
    return parse_teams(get(f"league/{league_key}/teams"))


def fetch_started_kickers(team_key, week):
    return parse_started_kickers(get(f"team/{team_key}/roster;week={week}"))
