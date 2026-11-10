"""JioFarm — GrizzlySMS API client."""

from __future__ import annotations

import threading
import time

import requests


class GrizzlyError(Exception):
    pass


class GrizzlySMS:
    """Minimal client for the GrizzlySMS stubs/handler_api.php endpoint."""

    BASE = "https://api.grizzlysms.com/stubs/handler_api.php"
    MIN_GAP = 1.2  # seconds between any two API calls, process-wide

    def __init__(self, api_key: str):
        self.key = api_key
        self._lock = threading.Lock()
        self._last = 0.0

    # ----------------------------------------------------------------- low level
    def _get(self, params: dict, retries: int = 4) -> str:
        params = {"api_key": self.key, **params}
        for attempt in range(1, retries + 1):
            with self._lock:
                wait = self.MIN_GAP - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.time()
            try:
                res = requests.get(self.BASE, params=params, timeout=20)
                if res.status_code == 429:
                    back = attempt * 3
                    time.sleep(back)
                    continue
                res.raise_for_status()
                return res.text.strip()
            except requests.RequestException:
                if attempt == retries:
                    raise
                time.sleep(2)
        raise GrizzlyError("GrizzlySMS request failed after retries.")

    # ---------------------------------------------------------------- high level
    def balance(self) -> float:
        out = self._get({"action": "getBalance"})
        if out.startswith("ACCESS_BALANCE:"):
            return float(out.split(":", 1)[1])
        raise GrizzlyError(f"balance error: {out}")

    def rent(self, max_price: float | None = None) -> tuple[str, str]:
        p: dict = {"action": "getNumber", "service": "jio", "country": 22}
        if max_price is not None:
            p["maxPrice"] = max_price
        out = self._get(p)
        if out.startswith("ACCESS_NUMBER:"):
            _, act_id, phone = out.split(":", 2)
            return act_id, phone
        if out.startswith("WRONG_MAX_PRICE:"):
            min_cost = out.split(":", 1)[1]
            try:
                min_cost_f = float(min_cost)
                raise GrizzlyError(f"Harga GrizzlySMS (${min_cost_f:.2f}) melebihi limit max-price (${max_price:.2f})")
            except ValueError:
                pass
        raise GrizzlyError(out)

    def status(self, act_id: str) -> tuple[str, str | None]:
        out = self._get({"action": "getStatus", "id": act_id})
        if out == "STATUS_WAIT_CODE":
            return "WAIT", None
        if out.startswith("STATUS_OK:"):
            return "OK", out.split(":", 1)[1]
        if out == "STATUS_CANCEL":
            return "CANCEL", None
        raise GrizzlyError(f"status error: {out}")

    def ready(self, act_id: str) -> None:
        self._get({"action": "setStatus", "id": act_id, "status": 1})

    def complete(self, act_id: str) -> None:
        self._get({"action": "setStatus", "id": act_id, "status": 6})

    def cancel(self, act_id: str) -> None:
        self._get({"action": "setStatus", "id": act_id, "status": 8})


def poll_otp(sms: GrizzlySMS, act_id: str, timeout: int = 120, interval: int = 5) -> str:
    """Poll GrizzlySMS until the OTP arrives or the deadline expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state, code = sms.status(act_id)
        if state == "OK" and code:
            return code
        if state == "CANCEL":
            raise GrizzlyError("activation cancelled upstream")
        time.sleep(interval)
    raise GrizzlyError(f"OTP timeout after {timeout}s")