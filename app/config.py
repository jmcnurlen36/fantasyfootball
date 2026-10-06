"""Settings, all read from environment variables (Fly secrets in production)."""
import os

LEAGUE_ID = os.environ.get("YAHOO_LEAGUE_ID", "746192")
CLIENT_ID = os.environ.get("YAHOO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YAHOO_CLIENT_SECRET", "")
# Must match the Redirect URI registered on the Yahoo developer app exactly.
REDIRECT_URI = os.environ.get("YAHOO_REDIRECT_URI", "https://localhost:8080")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
DATA_DIR = os.environ.get("DATA_DIR", "./data")
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "6"))
SCHEDULER = os.environ.get("SCHEDULER", "on") == "on"

# Used only if Yahoo's league settings don't report when playoffs start.
LAST_WEEK_FALLBACK = int(os.environ.get("LAST_REGULAR_SEASON_WEEK", "14"))

# First names of managers who are not part of the bet. They stay on the page, greyed out.
# This is only the starting point: the admin page has a checkbox per manager that overrides it.
NOT_IN_BET = [n.strip().lower() for n in
              os.environ.get("NOT_IN_BET", "Jen,Mike,Stephen,Alicia").split(",") if n.strip()]
