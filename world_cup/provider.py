import json
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class FootballDataError(RuntimeError):
    pass


class FootballDataClient:
    base_url = "https://api.football-data.org/v4"

    def __init__(self, api_token, timeout=15):
        self.api_token = api_token
        self.timeout = timeout

    def fetch_fixtures(self, *, from_date=None, to_date=None):
        params = {}
        if from_date:
            params["dateFrom"] = self._date_value(from_date)
        if to_date:
            params["dateTo"] = self._date_value(to_date)
        payload = self._get("/competitions/WC/matches", params)
        return payload.get("matches") or []

    @staticmethod
    def _date_value(value):
        return value.isoformat() if isinstance(value, date) else value

    def _get(self, path, params):
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(url, headers={"X-Auth-Token": self.api_token})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise FootballDataError(f"football-data.org HTTP {error.code}: {body}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise FootballDataError(f"football-data.org request failed: {error}") from error
