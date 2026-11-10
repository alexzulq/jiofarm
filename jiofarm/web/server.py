"""JioFarm — Web Server & Control Center Backend.

Provides a modern REST & WebSocket interface for controlling hunter workers,
monitoring live worker phases, viewing balance, managing settings, and exporting links.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Optional
import webbrowser

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from jiofarm.config import Config, load_config, save_env_config
from jiofarm.console import tg_send
from jiofarm.grizzly.refund import RefundWorker
from jiofarm.hunter import Phase, SMSProvider, WorkerState, create_provider, create_providers, hunt_once
from jiofarm.shield import install_doh_shield
from jiofarm.storage.store import Store


# ------------------------------------------------------------------- Models & Engine

class StartHuntRequest(BaseModel):
    concurrency: Optional[int] = None
    max_price: Optional[float] = None
    target: Optional[int] = None
    duration_minutes: Optional[int] = None
    count: Optional[int] = None


class ConfigUpdateRequest(BaseModel):
    provider: str
    grizzly_api_key: Optional[str] = None
    fivesim_api_key: Optional[str] = None
    grizzly_product: Optional[str] = "jio"
    fivesim_product: Optional[str] = "jiomart"
    max_price: float = 1.0
    concurrency: int = 2
    cancel_delay_seconds: float = 150.0
    otp_fail_delay_seconds: float = 420.0
    tg_bot_token: Optional[str] = ""
    tg_chat_id: Optional[str] = ""


class TestTelegramRequest(BaseModel):
    bot_token: str
    chat_id: str


class HunterEngine:
    """Thread-safe orchestrator managing background hunter threads for the Web UI."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status: str = "idle"  # "idle" | "running" | "stopping"
        self.start_time: Optional[float] = None
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.workers: list[WorkerState] = []
        self.found_links: list[str] = []
        self.done_count: int = 0
        self.target_links: Optional[int] = None
        self.duration_seconds: Optional[float] = None
        self.target_count: Optional[int] = None
        self.cached_balance: Optional[float] = None
        self.cached_balances: dict[str, Optional[float]] = {}
        self.last_balance_time: float = 0.0
        self.balance_error: Optional[str] = None
        self.refund_worker: Optional[RefundWorker] = None
        self.active_provider: Optional[SMSProvider] = None

        # Ring buffer for live logs
        self.logs: deque[dict[str, Any]] = deque(maxlen=400)
        self.ws_clients: set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add_log(self, level: str, message: str, wid: Optional[int] = None) -> None:
        entry = {
            "id": int(time.time() * 1000),
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,  # info, success, warning, error, refund
            "wid": wid,
            "message": message,
        }
        with self.lock:
            self.logs.append(entry)
        self._broadcast_ws({"type": "log", "data": entry})

    def _handle_refund_log(self, msg: str) -> None:
        self.add_log("refund", f"♻ {msg}")
        if "berhasil" in msg:
            threading.Thread(target=lambda: self.check_balance(force=True), daemon=True).start()
            self._broadcast_ws({"type": "state", "data": self.get_telemetry()})

    def _broadcast_ws(self, msg: dict[str, Any]) -> None:
        if not self.ws_clients or not self._loop:
            return
        payload = json.dumps(msg)
        for ws in list(self.ws_clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_text(payload), self._loop)
            except Exception:
                pass

    def check_balance(self, cfg: Optional[Config] = None, force: bool = False) -> Optional[float]:
        now = time.time()
        if not force and self.cached_balance is not None and (now - self.last_balance_time < 30.0):
            return self.cached_balance

        if cfg is None:
            cfg = load_config(strict=False)

        if not cfg.is_configured and not (cfg.provider in ("split", "both", "dual") and (cfg.has_grizzly or cfg.has_fivesim)):
            self.balance_error = "API Key belum diset"
            return None

        balances: dict[str, Optional[float]] = {"grizzly": None, "fivesim": None}
        errors: list[str] = []

        if cfg.provider in ("split", "both", "dual"):
            if cfg.has_grizzly:
                try:
                    from jiofarm.grizzly.client import GrizzlySMS
                    balances["grizzly"] = GrizzlySMS(cfg.grizzly_api_key).balance()
                except Exception as e:
                    errors.append(f"Grizzly: {e}")
            if cfg.has_fivesim:
                try:
                    from jiofarm.fivesim.client import FiveSim
                    balances["fivesim"] = FiveSim(cfg.fivesim_api_key).balance()
                except Exception as e:
                    errors.append(f"5SIM: {e}")

            valid_vals = [b for b in balances.values() if b is not None]
            total_bal = sum(valid_vals) if valid_vals else None
            with self.lock:
                self.cached_balances = balances
                self.cached_balance = total_bal
                self.last_balance_time = now
                self.balance_error = "; ".join(errors) if errors else None
            return total_bal

        try:
            prov = create_provider(cfg)
            bal = prov.balance()
            with self.lock:
                self.cached_balance = bal
                self.cached_balances = {
                    "grizzly": bal if cfg.provider == "grizzlysms" else None,
                    "fivesim": bal if cfg.provider == "fivesim" else None,
                }
                self.last_balance_time = now
                self.balance_error = None
            return bal
        except Exception as e:
            with self.lock:
                self.balance_error = str(e)
            return None

    def start_hunt(self, req: StartHuntRequest) -> dict[str, Any]:
        with self.lock:
            if self.status == "running":
                raise HTTPException(status_code=400, detail="Hunter sedang berjalan!")

            cfg = load_config(strict=False)
            if not cfg.is_configured and not (cfg.provider in ("split", "both", "dual") and (cfg.has_grizzly or cfg.has_fivesim)):
                raise HTTPException(
                    status_code=400,
                    detail=f"API Key untuk provider '{cfg.provider}' belum dikonfigurasi di Settings!"
                )

            # Apply runtime overrides
            if req.max_price is not None:
                cfg.max_price_override = req.max_price
            if req.concurrency is not None:
                cfg.concurrency_override = req.concurrency
            if req.target is not None:
                cfg.target = req.target
            if req.duration_minutes is not None:
                cfg.duration = req.duration_minutes * 60.0
            if req.count is not None:
                cfg.count = req.count

            try:
                install_doh_shield()
                prov_map = create_providers(cfg)
                if not prov_map:
                    raise ValueError(f"Tidak ada provider SMS yang aktif untuk '{cfg.provider}'")
                prov_keys = list(prov_map.keys())
                self.active_provider = prov_map[prov_keys[0]]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Gagal inisialisasi provider: {e}")

            store = Store(cfg.db_path)
            if self.refund_worker is None:
                self.refund_worker = RefundWorker(
                    self.active_provider,
                    log=self._handle_refund_log
                )
            else:
                self.refund_worker.sms = self.active_provider
                self.refund_worker.log = self._handle_refund_log

            workers_count = cfg.effective_concurrency
            self.workers = []
            for i in range(workers_count):
                assigned_prov_name = prov_keys[i % len(prov_keys)]
                self.workers.append(WorkerState(wid=i + 1, provider_name=assigned_prov_name))

            self.status = "running"
            self.start_time = time.time()
            self.stop_event.clear()
            self.found_links = []
            self.done_count = 0
            self.target_links = cfg.target
            self.duration_seconds = cfg.duration
            self.target_count = req.count
            self.threads = []

            slots = threading.Semaphore(workers_count)
            is_count_mode = bool(self.target_count and not (self.duration_seconds or self.target_links))

        prov_desc = f"{cfg.provider.upper()} ({' + '.join(prov_keys)})" if len(prov_keys) > 1 else cfg.provider.upper()
        self.add_log(
            "info",
            f"🚀 Memulai JioFarm Hunter | Provider: {prov_desc} | Workers: {workers_count} | Max Price: ${cfg.effective_max_price}"
        )

        def runner(ws: WorkerState) -> None:
            worker_prov = prov_map.get(ws.provider_name, self.active_provider)
            while not self.stop_event.is_set():
                with self.lock:
                    if self.duration_seconds and (time.time() - (self.start_time or 0)) >= self.duration_seconds:
                        break
                    if self.target_links and len(self.found_links) >= self.target_links:
                        break
                    if is_count_mode and self.done_count >= (self.target_count or 1):
                        break
                    self.done_count += 1
                    current_attempt = self.done_count

                self.add_log("info", f"Worker #{ws.wid} [{ws.provider_name}] memulai siklus #{current_attempt}", ws.wid)
                try:
                    link = hunt_once(worker_prov, store, self.refund_worker, slots, cfg, ws)
                except Exception as e:
                    ws.phase = Phase.ERROR
                    ws.error = str(e)
                    link = None

                if link:
                    with self.lock:
                        self.found_links.append(link)
                    self.add_log("success", f"🎯 LINK DITEMUKAN: {link}", ws.wid)
                else:
                    msg = ws.error if ws.error else "Tidak ada promo aktif"
                    self.add_log("warning" if ws.phase != Phase.ERROR else "error", f"Worker #{ws.wid} [{ws.provider_name}]: {msg}", ws.wid)

                if is_count_mode or self.stop_event.is_set():
                    break
                time.sleep(2.5)

            ws.phase = Phase.IDLE

        for ws in self.workers:
            t = threading.Thread(target=runner, args=(ws,), daemon=True)
            self.threads.append(t)
            t.start()

        # Watcher thread to auto-stop when targets/duration hit
        def watcher() -> None:
            while self.status == "running" and not self.stop_event.is_set():
                time.sleep(1.0)
                elapsed = time.time() - (self.start_time or 0)
                with self.lock:
                    hit_duration = bool(self.duration_seconds and elapsed >= self.duration_seconds)
                    hit_target = bool(self.target_links and len(self.found_links) >= self.target_links)
                    hit_count = bool(is_count_mode and self.done_count >= (self.target_count or 1))
                    all_dead = bool(is_count_mode and all(not t.is_alive() for t in self.threads))

                if hit_duration or hit_target or hit_count or all_dead:
                    self.stop_hunt()
                    reason = "Batas durasi tercapai" if hit_duration else ("Target link tercapai" if hit_target else "Target attempt selesai")
                    self.add_log("info", f"🏁 Perburuan selesai ({reason}). Menunggu refund worker...")
                    break

        threading.Thread(target=watcher, daemon=True).start()
        return self.get_telemetry()

    def stop_hunt(self) -> dict[str, Any]:
        with self.lock:
            if self.status != "running":
                return self.get_telemetry()
            self.status = "stopping"
            self.stop_event.set()

        self.add_log("warning", "🛑 Menghentikan hunter... Menunggu worker menyelesaikan tugas.")

        def cleanup() -> None:
            for t in self.threads:
                t.join(timeout=8)
            with self.lock:
                self.status = "idle"
                for w in self.workers:
                    w.phase = Phase.IDLE

            pending = self.refund_worker.pending if self.refund_worker else 0
            if pending > 0:
                self.add_log(
                    "info",
                    f"✅ Hunter dihentikan. Proses auto-refund ({pending} nomor) TETAP BERJALAN di background sampai saldo kembali."
                )
            else:
                self.add_log("info", "✅ Semua worker telah berhenti.")
            self._broadcast_ws({"type": "state", "data": self.get_telemetry()})

        threading.Thread(target=cleanup, daemon=True).start()
        return self.get_telemetry()

    def get_telemetry(self) -> dict[str, Any]:
        cfg = load_config(strict=False)
        elapsed = (time.time() - self.start_time) if (self.status == "running" and self.start_time) else 0.0

        workers_data = []
        for w in self.workers:
            workers_data.append({
                "wid": w.wid,
                "provider_name": w.provider_name,
                "phase": w.phase.name,
                "phone": w.phone,
                "act_id": w.act_id,
                "otp": w.otp,
                "logged_in": w.logged_in,
                "link": w.link,
                "error": w.error,
                "attempts": w.attempts,
            })

        store = Store(cfg.db_path)
        stats = store.stats()

        return {
            "status": self.status,
            "elapsed_seconds": int(elapsed),
            "provider": cfg.provider,
            "is_configured": cfg.is_configured,
            "balance": self.cached_balance,
            "balances": self.cached_balances,
            "balance_error": self.balance_error,
            "refunds_pending": self.refund_worker.pending if self.refund_worker else 0,
            "done_count": self.done_count,
            "current_found": len(self.found_links),
            "total_links_all_time": stats["links"],
            "total_hunts_all_time": stats["hunts"],
            "total_logins_all_time": stats["logins"],
            "workers": workers_data,
            "concurrency": cfg.effective_concurrency,
            "max_price": cfg.effective_max_price,
            "telegram_enabled": cfg.telegram_enabled,
        }


engine = HunterEngine()
app = FastAPI(title="JioFarm Web Dashboard", description="Live Control Center for Google AI Pro Hunter")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ------------------------------------------------------------------- API Endpoints

@app.on_event("startup")
async def startup_event() -> None:
    install_doh_shield()
    engine.set_event_loop(asyncio.get_event_loop())
    # Asynchronously refresh initial balance
    threading.Thread(target=lambda: engine.check_balance(force=True), daemon=True).start()


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    index_file = TEMPLATES_DIR / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/api/telemetry")
async def get_telemetry() -> dict[str, Any]:
    return engine.get_telemetry()


@app.get("/api/logs")
async def get_logs() -> list[dict[str, Any]]:
    with engine.lock:
        return list(engine.logs)


@app.post("/api/hunter/start")
async def start_hunter(req: StartHuntRequest) -> dict[str, Any]:
    return engine.start_hunt(req)


@app.post("/api/hunter/stop")
async def stop_hunter() -> dict[str, Any]:
    return engine.stop_hunt()


@app.get("/api/balance/refresh")
async def refresh_balance() -> dict[str, Any]:
    bal = engine.check_balance(force=True)
    return {
        "balance": bal,
        "balances": engine.cached_balances,
        "error": engine.balance_error,
        "provider": load_config(strict=False).provider,
    }


@app.get("/api/links")
async def get_links() -> dict[str, Any]:
    cfg = load_config(strict=False)
    store = Store(cfg.db_path)
    links = store.all_links_detailed()
    return {"links": links, "total": len(links)}


@app.get("/api/links/export")
async def export_links(format: str = "txt") -> Response:
    cfg = load_config(strict=False)
    store = Store(cfg.db_path)
    links_detailed = store.all_links_detailed()

    if format == "json":
        content = json.dumps(links_detailed, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=jiofarm_links.json"},
        )
    elif format == "csv":
        import io, csv
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["ID", "Phone", "ActivationID", "OTP", "Link", "CreatedAt"])
        for row in links_detailed:
            writer.writerow([row["id"], row["phone"], row["activation_id"], row["otp"], row["link"], row["created_at"]])
        return Response(
            content=out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=jiofarm_links.csv"},
        )
    else:
        # plain list of urls
        plain = "\n".join(r["link"] for r in links_detailed)
        return PlainTextResponse(
            content=plain,
            headers={"Content-Disposition": "attachment; filename=jiofarm_links.txt"},
        )


@app.get("/api/hunts/recent")
async def get_recent_hunts(limit: int = 30) -> dict[str, Any]:
    cfg = load_config(strict=False)
    store = Store(cfg.db_path)
    hunts = store.recent_hunts(limit=limit)
    return {"hunts": hunts}


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    cfg = load_config(strict=False)
    
    def mask_key(k: str) -> str:
        if not k or k == "your_api_key_here":
            return ""
        if len(k) <= 8:
            return "••••••••"
        return k[:4] + "••••••••" + k[-4:]

    return {
        "provider": cfg.provider,
        "is_configured": cfg.is_configured,
        "grizzly_api_key_masked": mask_key(os.getenv("GRIZZLY_API_KEY", "")),
        "fivesim_api_key_masked": mask_key(os.getenv("FIVESIM_API_KEY", "")),
        "has_grizzly_key": bool(os.getenv("GRIZZLY_API_KEY", "").strip() and os.getenv("GRIZZLY_API_KEY", "") != "your_api_key_here" and "••" not in os.getenv("GRIZZLY_API_KEY", "")),
        "has_fivesim_key": bool(os.getenv("FIVESIM_API_KEY", "").strip() and os.getenv("FIVESIM_API_KEY", "") != "your_api_key_here" and "••" not in os.getenv("FIVESIM_API_KEY", "")),
        "grizzly_product": os.getenv("GRIZZLY_PRODUCT", "jio"),
        "fivesim_product": os.getenv("FIVESIM_PRODUCT", "jiomart"),
        "max_price": cfg.max_price,
        "concurrency": cfg.concurrency,
        "cancel_delay_seconds": cfg.cancel_delay,
        "otp_fail_delay_seconds": cfg.otp_fail_delay,
        "tg_bot_token_masked": mask_key(cfg.tg_bot_token),
        "tg_chat_id": cfg.tg_chat_id,
        "telegram_enabled": cfg.telegram_enabled,
        "db_path": cfg.db_path,
    }


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest) -> dict[str, Any]:
    updates: dict[str, str] = {
        "PROVIDER": req.provider.strip().lower(),
        "MAX_PRICE": str(req.max_price),
        "CONCURRENCY": str(req.concurrency),
        "CANCEL_DELAY_SECONDS": str(int(req.cancel_delay_seconds)),
        "OTP_FAIL_DELAY_SECONDS": str(int(req.otp_fail_delay_seconds)),
    }
    if req.grizzly_api_key and "••" not in req.grizzly_api_key and req.grizzly_api_key != "your_api_key_here":
        updates["GRIZZLY_API_KEY"] = req.grizzly_api_key.strip()
    if req.fivesim_api_key and "••" not in req.fivesim_api_key and req.fivesim_api_key != "your_api_key_here":
        updates["FIVESIM_API_KEY"] = req.fivesim_api_key.strip()
    if req.grizzly_product:
        updates["GRIZZLY_PRODUCT"] = req.grizzly_product.strip()
    if req.fivesim_product:
        updates["FIVESIM_PRODUCT"] = req.fivesim_product.strip()
    if req.tg_bot_token and "••" not in req.tg_bot_token:
        updates["TG_BOT_TOKEN"] = req.tg_bot_token.strip()
    if req.tg_chat_id:
        updates["TG_CHAT_ID"] = req.tg_chat_id.strip()

    save_env_config(updates)
    engine.add_log("info", f"⚙️ Konfigurasi diperbarui (.env disimpan)")
    # Refresh balance with new config
    threading.Thread(target=lambda: engine.check_balance(force=True), daemon=True).start()
    return {"success": True, "message": "Konfigurasi berhasil disimpan ke .env"}


@app.post("/api/test-telegram")
async def test_telegram(req: TestTelegramRequest) -> dict[str, Any]:
    token = req.bot_token.strip()
    chat_id = req.chat_id.strip()
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Token Bot dan Chat ID harus diisi")

    msg = "🦁 *JioFarm Web Control Center*\n\n✅ Notifikasi Telegram berhasil terhubung! Siap berburu link Google AI Pro."
    try:
        tg_send(msg, token, chat_id)
        engine.add_log("success", "✅ Pesan tes Telegram berhasil dikirim!")
        return {"success": True, "message": "Pesan tes berhasil dikirim ke Telegram!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengirim Telegram: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    engine.ws_clients.add(websocket)
    try:
        # Send initial state
        await websocket.send_text(json.dumps({
            "type": "init",
            "state": engine.get_telemetry(),
            "logs": list(engine.logs)[-100:]
        }))
        while True:
            # Keep connection alive & listen for client pings/messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif data == "state":
                await websocket.send_text(json.dumps({"type": "state", "data": engine.get_telemetry()}))
    except WebSocketDisconnect:
        pass
    finally:
        engine.ws_clients.discard(websocket)


# ------------------------------------------------------------------- Launcher

def run_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    """Launch the FastAPI server and optionally open the browser."""
    url = f"http://{host}:{port}"
    print(f"\n🦁 JioFarm Web Dashboard running at: {url}\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="info")
