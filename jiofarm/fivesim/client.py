"""JioFarm — 5SIM.net API client.

5SIM API v1 reference:
- Base: https://5sim.net/v1
- Auth: Bearer token in Authorization header
- Buy:  GET /user/buy/activation/{country}/{operator}/{product}
- SMS:  GET /user/check/{id}
- Cancel: GET /user/cancel/{id}
"""

from __future__ import annotations

import threading
import time

import requests


class FiveSimError(Exception):
    pass


class FiveSim:
    """Minimal client for the 5SIM.net API."""

    BASE = "https://5sim.net/v1"
    MIN_GAP = 1.0  # seconds between API calls

    def __init__(self, api_key: str):
        self.key = api_key
        self._lock = threading.Lock()
        self._last = 0.0

    # ----------------------------------------------------------------- low level
    def _get(self, path: str, retries: int = 3) -> dict | str:
        url = f"{self.BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
        }
        for attempt in range(1, retries + 1):
            with self._lock:
                wait = self.MIN_GAP - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.time()
            try:
                res = requests.get(url, headers=headers, timeout=20)
                if res.status_code == 401:
                    raise FiveSimError("5SIM Unauthorized (401) — Token JWT tidak valid")
                if res.status_code == 429:
                    back = attempt * 3
                    time.sleep(back)
                    continue
                if res.status_code >= 400:
                    raw_msg = res.text.strip()
                    if not raw_msg or raw_msg.startswith("<!DOCTYPE") or "<html" in raw_msg:
                        raw_msg = f"{res.status_code} {res.reason}"
                    if "no free phones" in raw_msg.lower():
                        raise FiveSimError("5SIM: Stok nomor kosong untuk operator ini ('no free phones')")
                    if "not enough" in raw_msg.lower() or "balance" in raw_msg.lower():
                        raise FiveSimError(f"5SIM: Saldo akun tidak mencukupi ({raw_msg})")
                    raise FiveSimError(f"5SIM Error ({res.status_code}): {raw_msg}")

                ct = res.headers.get("content-type", "")
                if "json" in ct:
                    return res.json()
                text_out = res.text.strip()
                if "no free phones" in text_out.lower():
                    raise FiveSimError("5SIM: Stok nomor kosong ('no free phones')")
                return text_out
            except FiveSimError:
                raise
            except requests.RequestException as e:
                if attempt == retries:
                    raise FiveSimError(f"5SIM request failed: {e}")
                time.sleep(2)
        raise FiveSimError("5SIM request failed after retries.")

    # ---------------------------------------------------------------- high level
    def balance(self) -> float:
        """Return account balance in USD."""
        data = self._get("/user/profile")
        if isinstance(data, dict):
            return float(data.get("balance", 0))
        raise FiveSimError(f"balance error: {data}")

    def _get_candidate_operators(
        self, country: str = "india", product: str = "jiomart", max_price: float | None = None
    ) -> tuple[list[str], float | None]:
        """Fetch real-time stock & prices to find cheapest operators within max_price."""
        url = f"{self.BASE}/guest/prices?country={country}&product={product}"
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return [], None
        data = res.json().get(country, {}).get(product, {})
        candidates: list[tuple[float, str]] = []
        cheapest_cost: float | None = None
        for op, info in data.items():
            cost = float(info.get("cost", 9999.0))
            count = int(info.get("count", 0))
            if count > 0:
                if cheapest_cost is None or cost < cheapest_cost:
                    cheapest_cost = cost
                if max_price is None or cost <= max_price:
                    candidates.append((cost, op))
        candidates.sort()  # cheapest first
        return [op for _, op in candidates], cheapest_cost

    def rent(self, max_price: float | None = None) -> tuple[str, str]:
        """Buy an activation strictly obeying max_price (GrizzlySMS-compatible alias)."""
        country = "india"
        product = "jiomart"

        try:
            operators, cheapest_cost = self._get_candidate_operators(country, product, max_price)
            if not operators and cheapest_cost is not None and max_price is not None and cheapest_cost > max_price:
                raise FiveSimError(
                    f"Harga 5SIM (${cheapest_cost:.2f}) melebihi limit max-price (${max_price:.2f})"
                )
            if not operators and cheapest_cost is None:
                raise FiveSimError(f"Stok nomor 5SIM untuk {product} ({country}) sedang kosong")

            # Try candidate operators starting with cheapest
            last_err = ""
            for op in operators:
                try:
                    return self.buy(country=country, operator=op, product=product, max_price=max_price)
                except FiveSimError as e:
                    last_err = str(e)
                    continue

            if last_err:
                raise FiveSimError(last_err)
        except FiveSimError:
            raise
        except Exception:
            # If price check failed, fallback to direct purchase with safety price check
            pass

        return self.buy(country=country, operator="any", product=product, max_price=max_price)

    def buy(
        self,
        country: str = "india",
        operator: str = "any",
        product: str = "jiomart",
        max_price: float | None = None,
    ) -> tuple[str, str]:
        """Buy an activation. Returns (activation_id, phone_number)."""
        path = f"/user/buy/activation/{country}/{operator}/{product}"
        data = self._get(path)
        if isinstance(data, dict):
            aid = str(data.get("id", ""))
            phone = str(data.get("phone", ""))
            price = float(data.get("price", 0.0))

            # Emergency hard cap: If 5SIM charged higher than max_price, cancel immediately!
            if max_price is not None and price > max_price and aid:
                try:
                    self.cancel(aid)
                except Exception:
                    pass
                raise FiveSimError(
                    f"5SIM membebankan harga ${price:.2f} yang melebihi max-price (${max_price:.2f}). Dibatalkan otomatis."
                )

            if aid and phone:
                return aid, phone
        if isinstance(data, str) and "no free phones" in data.lower():
            raise FiveSimError(f"5SIM: Operator '{operator}' sedang kehabisan stok ('no free phones')")
        raise FiveSimError(f"buy error: {data}")

    def ready(self, act_id: str) -> None:
        """5SIM auto-activates — no-op."""

    def complete(self, act_id: str) -> None:
        """Finish an activation on 5SIM."""
        try:
            self._get(f"/user/finish/{act_id}")
        except Exception:
            pass

    def status(self, act_id: str) -> tuple[str, str | None]:
        """GrizzlySMS-compatible alias for check()."""
        raw_status, code = self.check(act_id)
        # Map 5SIM statuses to GrizzlySMS format
        MAP = {
            "PENDING": "WAIT",
            "RECEIVED": "OK",
            "TIMEOUT": "CANCEL",
            "CANCELED": "CANCEL",
            "BANNED": "CANCEL",
            "FINISHED": "OK",
        }
        mapped = MAP.get(raw_status, "WAIT")
        return mapped, code

    def check(self, act_id: str) -> tuple[str, str | None]:
        """Check for SMS. Returns (status, code_or_None).

        Status values: 'PENDING', 'RECEIVED', 'TIMEOUT', 'CANCELED', 'BANNED'
        """
        data = self._get(f"/user/check/{act_id}")
        if isinstance(data, dict):
            status = str(data.get("status", "PENDING"))
            sms_list = data.get("sms", [])
            code = None
            if sms_list and isinstance(sms_list, list):
                code = sms_list[0].get("code") if isinstance(sms_list[0], dict) else None
            return status, code
        return "PENDING", None

    def cancel(self, act_id: str) -> None:
        """Cancel an activation (refund)."""
        self._get(f"/user/cancel/{act_id}")


def poll_sms(client: FiveSim, act_id: str, timeout: int = 120, interval: int = 5) -> str:
    """Poll 5SIM until the SMS arrives or the deadline expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, code = client.check(act_id)
        if status == "RECEIVED" and code:
            return code
        if status in ("CANCELED", "TIMEOUT", "BANNED"):
            raise FiveSimError(f"activation {status}")
        time.sleep(interval)
    raise FiveSimError(f"SMS timeout after {timeout}s")