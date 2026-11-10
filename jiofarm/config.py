"""JioFarm — centralised configuration from .env and CLI args."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _find_env() -> Path:
    """Look for .env next to the project root, falling back to cwd."""
    for base in (Path(__file__).resolve().parent.parent, Path.cwd()):
        candidate = base / ".env"
        if candidate.exists():
            return candidate
    return Path(".env")


def save_env_config(updates: dict[str, str]) -> Path:
    """Save or update key-values in .env file."""
    env_path = _find_env()
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    elif Path(".env.example").exists():
        lines = Path(".env.example").read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    target_path = Path.cwd() / ".env" if not env_path.exists() else env_path
    target_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    load_dotenv(target_path, override=True)
    return target_path


def load_config(strict: bool = True) -> "Config":
    """Load .env and return a populated Config instance."""
    env_path = _find_env()
    if env_path.exists():
        load_dotenv(env_path, override=True)

    provider = os.getenv("PROVIDER", "grizzlysms").strip().lower()
    grizzly_api_key = os.getenv("GRIZZLY_API_KEY", "").strip()
    fivesim_api_key = os.getenv("FIVESIM_API_KEY", "").strip()
    grizzly_product = os.getenv("GRIZZLY_PRODUCT", "jio").strip()
    fivesim_product = os.getenv("FIVESIM_PRODUCT", "jiomart").strip()

    if provider == "grizzlysms":
        api_key = grizzly_api_key
        if strict and (not api_key or api_key == "your_api_key_here"):
            msg = (
                "GRIZZLY_API_KEY belum diset di .env\n"
                "  1. Buka https://grizzlysms.com — daftar & topup\n"
                "  2. Copy API key dari dashboard\n"
                "  3. Paste ke .env: GRIZZLY_API_KEY=xxxx"
            )
            raise SystemExit(msg)
        product = grizzly_product
    elif provider == "fivesim":
        api_key = fivesim_api_key
        if strict and (not api_key or api_key == "your_api_key_here"):
            msg = (
                "FIVESIM_API_KEY belum diset di .env\n"
                "  1. Buka https://5sim.net — daftar & topup\n"
                "  2. Copy API key (JWT token) dari dashboard\n"
                "  3. Paste ke .env: FIVESIM_API_KEY=xxxx"
            )
            raise SystemExit(msg)
        product = fivesim_product
    elif provider in ("split", "both", "dual"):
        api_key = grizzly_api_key or fivesim_api_key
        product = "jio"
        if strict:
            has_g = bool(grizzly_api_key and grizzly_api_key != "your_api_key_here")
            has_5 = bool(fivesim_api_key and fivesim_api_key != "your_api_key_here")
            if not has_g and not has_5:
                raise SystemExit("PROVIDER=split memerlukan minimal salah satu atau kedua API Key (GRIZZLY_API_KEY dan FIVESIM_API_KEY)!")
    else:
        if strict:
            raise SystemExit(f"PROVIDER tidak dikenal: '{provider}'. Pilih: grizzlysms, fivesim, split")
        api_key = ""
        product = "jio"

    return Config(
        provider=provider,
        api_key=api_key,
        grizzly_api_key=grizzly_api_key,
        fivesim_api_key=fivesim_api_key,
        grizzly_product=grizzly_product,
        fivesim_product=fivesim_product,
        product=product,
        max_price=float(os.getenv("MAX_PRICE", "1.0")),
        cancel_delay=float(os.getenv("CANCEL_DELAY_SECONDS", "150")),
        otp_fail_delay=float(os.getenv("OTP_FAIL_DELAY_SECONDS", "420")),
        concurrency=int(os.getenv("CONCURRENCY", "2")),
        db_path=os.getenv("DB_PATH", "results.db"),
        tg_bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
        tg_chat_id=os.getenv("TG_CHAT_ID", "").strip(),
    )


@dataclass
class Config:
    """All runtime configuration, sourced from .env and overridden by CLI args."""

    provider: str = "grizzlysms"
    api_key: str = ""
    grizzly_api_key: str = ""
    fivesim_api_key: str = ""
    grizzly_product: str = "jio"
    fivesim_product: str = "jiomart"
    product: str = "jio"  # GrizzlySMS: "jio", 5SIM: "jiomart"
    max_price: float = 1.0
    cancel_delay: float = 150.0
    otp_fail_delay: float = 420.0
    concurrency: int = 2
    db_path: str = "results.db"

    # telegram (optional)
    tg_bot_token: str = ""
    tg_chat_id: str = ""

    # runtime overrides (set by CLI)
    max_price_override: float | None = field(default=None, repr=False)
    target: int | None = field(default=None, repr=False)
    duration: float | None = field(default=None, repr=False)
    count: int = field(default=1, repr=False)
    concurrency_override: int | None = field(default=None, repr=False)

    @property
    def effective_max_price(self) -> float | None:
        if self.max_price_override is not None:
            return self.max_price_override
        return self.max_price

    @property
    def effective_concurrency(self) -> int:
        return self.concurrency_override or self.concurrency

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.tg_bot_token and self.tg_chat_id)

    @property
    def has_grizzly(self) -> bool:
        return bool(self.grizzly_api_key and self.grizzly_api_key != "your_api_key_here" and "••" not in self.grizzly_api_key)

    @property
    def has_fivesim(self) -> bool:
        return bool(self.fivesim_api_key and self.fivesim_api_key != "your_api_key_here" and "••" not in self.fivesim_api_key)

    @property
    def is_configured(self) -> bool:
        if self.provider in ("split", "both", "dual"):
            return self.has_grizzly and self.has_fivesim
        elif self.provider == "fivesim":
            return self.has_fivesim
        return self.has_grizzly