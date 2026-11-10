"""JioFarm — GrizzlySMS Refund Worker.

Background thread that cancels failed activations to reclaim balance.

Two modes:
- **normal** — wait the full delay, then cancel (for OTP timeout cases)
- **aggressive** — retry every 30s starting immediately, cancel as soon as the
  GrizzlySMS lock window opens (for fast-fail cases like "not a subscriber")
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Protocol


class Cancellable(Protocol):
    """Anything that can cancel an activation."""
    def cancel(self, act_id: str) -> None: ...


# How often to retry in aggressive mode (seconds)
AGGRESSIVE_INTERVAL = 30


class RefundWorker:
    """Cancels failed activations after their lock window to reclaim balance."""

    def __init__(self, sms: Cancellable | None = None, log: Callable[[str], None] | None = None):
        self.sms = sms
        self.log = log or (lambda _: None)
        self.q: "queue.Queue[tuple[str, float, bool, Cancellable | None]]" = queue.Queue()
        self.pending = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def schedule(
        self,
        act_id: str,
        delay: float,
        aggressive: bool = False,
        sms_client: Cancellable | None = None,
    ) -> None:
        """Schedule a refund.

        Args:
            act_id: The activation ID to cancel.
            delay: Seconds to wait before first cancel attempt.
            aggressive: If True, try every 30s; if False, wait full delay once.
            sms_client: Specific SMS provider client to cancel on (default: self.sms).
        """
        with self._lock:
            self.pending += 1
        client = sms_client or self.sms
        self.q.put((act_id, time.time() + delay, aggressive, client))
        mode = "aggressive" if aggressive else "normal"
        self.log(f"refund #{act_id[-8:]} dijadwalkan ({mode}, {int(delay)}s)")

    def _loop(self) -> None:
        while True:
            time.sleep(2)
            due_now = time.time()
            batch: list[tuple[str, float, bool, Cancellable | None]] = []
            while True:
                try:
                    batch.append(self.q.get_nowait())
                except queue.Empty:
                    break

            remaining: list[tuple[str, float, bool, Cancellable | None]] = []
            for act_id, fire_at, aggressive, client in batch:
                if due_now >= fire_at:
                    active_sms = client or self.sms
                    try:
                        if active_sms is None:
                            raise ValueError("Tidak ada client SMS yang diset untuk refund")
                        active_sms.cancel(act_id)
                        self.log(f"refund #{act_id[-8:]} berhasil ✓")
                        with self._lock:
                            self.pending -= 1
                    except Exception as e:
                        err = str(e)
                        # retry: aggressive = every 30s, normal = every 10s
                        retry_delay = AGGRESSIVE_INTERVAL if aggressive else 10
                        self.log(f"refund #{act_id[-8:]} gagal: {err} — retry {int(retry_delay)}s")
                        remaining.append((act_id, time.time() + retry_delay, aggressive, client))
                else:
                    remaining.append((act_id, fire_at, aggressive, client))

            for item in remaining:
                self.q.put(item)

    def wait_all(self) -> None:
        """Block until all pending refunds are processed."""
        while True:
            with self._lock:
                if self.pending <= 0:
                    return
            time.sleep(1)