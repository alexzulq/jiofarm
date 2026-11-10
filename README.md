# 🦁 JioFarm

<div align="center">

**Google AI Pro / Gemini Pro Link Hunter**

*Panen link redeem Google AI Pro dari Jio selfcare secara otomatis*

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Rich](https://img.shields.io/badge/terminal-rich-purple.svg)](https://github.com/Textualize/rich)

</div>

---

## 📖 Apa Ini?

JioFarm adalah tool otomatis yang:
1. **Menyewa** nomor virtual Jio (India) dari berbagai SMS provider
2. **Login** ke Jio selfcare pakai OTP yang diterima nomor tersebut
3. **Berburu** link redeem Google AI Pro / Gemini Pro dari API subscription Jio
4. **Notifikasi** ke Telegram begitu link ditemukan

Dilengkapi **live dashboard** berbasis Rich yang menampilkan status worker secara real-time.

**Multi-provider:** JioFarm punya arsitektur modular yang mendukung berbagai SMS provider. Ganti provider tinggal ubah 1 baris di `.env` — tanpa ganti kode.

---

## 🖥️ Live Dashboard Preview

```
┌─ 🦁 JioFarm Hunter ───────────────────────────────────────────────┐
│ workers: 2 | max-price: $0.5 | refund pending: 0                   │
│ ⏱ 45s elapsed | 💰 $2.50 | 🎯 1 links                              │
└────────────────────────────────────────────────────────────────────┘
┌─ Workers ───────────────────────────┐ ┌─ 🎯 Links Found ──────────┐
│ W  Phase          Phone    Status   │ │ https://serviceactivation. │
│ 1  ✅ DONE       +91 9876  LINK!    │ │ google.com/...             │
│ 2  ⏳ WAITING_OTP +91 5432  wait... │ │                            │
└─────────────────────────────────────┘ └────────────────────────────┘
┌─ Ctrl+C to stop ──────────────────────────────────────────────────┐
```

---

## 📡 Memilih Provider — **PENTING!**

### ⚠️ Provider = Faktor Penentu Hasil

Jangan anggap remeh pemilihan provider. **Kualitas nomor yang disewa langsung mempengaruhi seberapa sering kamu dapat link.** Berikut faktornya:

| Faktor | Dampak |
|---|---|
| **Nomor bekas / recycled** | Nomor yang sudah dipakai user lain → kemungkinan besar sudah klaim promo → **link rate turun drastis** |
| **Nomor fresh / virgin** | Nomor baru yang belum pernah klaim → **link rate tinggi** |
| **Stok tersedia** | Provider dengan stok konsisten → farming lancar tanpa nunggu |
| **OTP delivery** | Provider yang OTP-nya cepat masuk → siklus hunt lebih efisien |
| **Harga per nomor** | Lebih murah = bisa lebih banyak attempt per dollar |

### 🔌 Provider Bawaan

JioFarm sudah include client untuk 2 provider:

| Provider | Status | Produk | Harga Estimasi | Catatan |
|---|---|---|---|---|
| **Split Dual** | ⚡ **Active** | `both` | Hybrid | Menjalankan GrizzlySMS & 5SIM bersamaan (Worker #1, #3 on 5SIM; Worker #2, #4 on Grizzly) |
| **GrizzlySMS** | ✅ Ready | `jio` | $0.20–$1.00 | Stabil, OTP reliable, API simpel |
| **5SIM** | ✅ Ready | `jiomart` | ~$0.05 | Sangat murah, token JWT |

### 🔄 Cara Ganti Provider & Jalankan Keduanya (Split Dual)

Cukup edit `.env` atau atur lewat **Web Dashboard**:

```env
# Pilih provider: split (keduanya), grizzlysms, atau fivesim
PROVIDER=split

# Masukkan kedua API Key
GRIZZLY_API_KEY=key_kamu_disini
FIVESIM_API_KEY=token_jwt_kamu_disini
```

Jalankan lewat Web Dashboard:
```bash
python -m jiofarm web
```
Atau lewat terminal CLI:
```bash
python -m jiofarm run --concurrency 4 --max-price 0.5
```

### 🧩 Arsitektur Multi-Provider

JioFarm pakai **Protocol interface** (`SMSProvider`) — semua provider cukup implementasi method yang sama:

```
                 ┌─────────────┐
                 │  hunter.py  │  ← orchestrator (generic)
                 └──────┬──────┘
                        │ SMSProvider Protocol
            ┌───────────┼───────────┐
      ┌─────┴─────┐           ┌─────┴─────┐
      │ GrizzlySMS │           │  FiveSim  │   ← built-in
      └───────────┘           └───────────┘
                                  │
                            ┌─────┴─────┐
                            │  Provider  │   ← gampang ditambah
                            │  Baru      │
                            └───────────┘
```

### 🔍 Provider Alternatif yang Bisa Kamu Coba

Jio nggak cuma ada di GrizzlySMS. Berikut provider lain yang punya layanan nomor India — **luangkan waktu riset provider yang paling cocok:**

| Provider | URL | Catatan |
|---|---|---|
| **SMS-Activate** | sms-activate.org | Banyak pilihan operator India, harga kompetitif, API matang |
| **SMSPool** | smspool.net | Stok India lumayan, API well-documented |
| **SMSMan** | sms-man.com | Ada Jio di katalog, harganya bervariasi |
| **5SIM** | 5sim.net | Client sudah built-in, tapi jiomart API-nya flaky — cek berkala |
| **TextVerified** | textverified.com | US-focused tapi kadang ada India |
| **SMSCodes** | smscodes.io | Relatif baru, harga murah |

### 🛠️ Cara Nambah Provider Sendiri

JioFarm didesain supaya gampang ditambah provider baru. Buat file di `jiofarm/<nama_provider>/client.py`:

```python
class ProviderBaru:
    def balance(self) -> float: ...
    def rent(self, max_price: float | None = None) -> tuple[str, str]: ...
    def status(self, act_id: str) -> tuple[str, str | None]: ...
    def ready(self, act_id: str) -> None: ...
    def complete(self, act_id: str) -> None: ...
    def cancel(self, act_id: str) -> None: ...
```

Lalu daftarin di factory function di `hunter.py`. Method-method ini mengikuti Protocol `SMSProvider` — nggak perlu inheritance, cukup duck-typing.

### 🎯 Tips Mencari Provider Bagus

1. **Cek katalog mereka** — pastikan ada "Jio" (bukan cuma "MyJio" atau "India Any")
2. **Tes beli manual** — coba beli 1 nomor lewat web dulu sebelum topup besar. Kalau sering "no numbers", skip
3. **Cek komunitas** — forum seperti BlackHatWorld, LowEndTalk, atau grup Telegram sering ada review provider
4. **Bandingkan harga** — $0.05 vs $0.50 per nomor = 10x lebih banyak attempt dengan budget yang sama
5. **OTP delivery time** — provider yang OTP-nya lambat bikin siklus hunt lebih panjang, less efficient
6. **Refund policy** — provider yang auto-refund nomor gagal lebih hemat dalam jangka panjang

> **Realita:** Nggak semua nomor Jio dapat promo Google AI Pro — ini pure RNG. Tapi nomor fresh dari provider yang jarang dipakai hunter lain punya chance lebih tinggi. **Provider yang sama yang dipakai rame-rame hunter lain = nomornya sudah banyak yang klaim = link rate rendah.**

---

## 📋 Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.9+ | [Download](https://www.python.org/downloads/) |
| Akun SMS Provider | — | Lihat [§ Memilih Provider](#-memilih-provider---penting) di atas |
| API Key Provider | — | Dari dashboard provider masing-masing |
| Telegram Bot *(optional)* | — | Buat notifikasi real-time |

---

## 🚀 Install — Semua Platform

### 1. Clone / Download

```bash
git clone https://github.com/hirotomasato/jiofarm.git
cd jiofarm
```

Atau download ZIP dan extract.

### 2. Buat Virtual Environment

**Windows (PowerShell / cmd):**
```powershell
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -e .
```

Ini akan menginstall semua dependency: `requests`, `python-dotenv`, `rich`, `typer`.

### 4. Setup `.env`

Copy `.env.example` ke `.env`:

**Windows:**
```powershell
copy .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

Buka `.env` dan isi:

```env
# Pilih provider
PROVIDER=grizzlysms

# API key provider (sesuai pilihan di atas)
GRIZZLY_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Opsional: batasan harga & concurrency
MAX_PRICE=1.0
CONCURRENCY=2
```

> **Dapat API key:** Login ke provider masing-masing → Dashboard → API Key / Token

---

## 🎮 Cara Pakai

### Web Dashboard (Paling Mudah 🌟)

Jalankan server web dan buka control center di browser:
```bash
python -m jiofarm web
```
Akses dashboard di browser pada `http://localhost:8000` untuk kontrol visual, live telemetry worker, dan links vault.

### Interactive Menu

```bash
python -m jiofarm
```

Tampil menu pilihan:
```
┌──────────────────────────────────────┐
│ 🦁  JioFarm — Google AI Pro Hunter  │
│ Panen link redeem Gemini Pro dari Jio│
└──────────────────────────────────────┘

  0   Launch Web Dashboard (Rekomendasi 🌟)
  1   Run Hunter (Terminal Rich)
  2   Check Balance
  3   View Stats
  4   Export Links
  5   Quit
```

### Command Langsung

```bash
# Cek saldo provider
python -m jiofarm balance

# 1x hunt dengan max price $0.5 (mode hemat)
python -m jiofarm run --max-price 0.5

# 5x hunt paralel
python -m jiofarm run --count 5 --concurrency 2

# Jalan selama 6 jam, max price $0.5
python -m jiofarm run --duration 6h --max-price 0.5

# Berhenti setelah dapat 3 link
python -m jiofarm run --target 3 --max-price 0.5

# Lihat statistik
python -m jiofarm stats

# Export link ke file
python -m jiofarm links --out links.txt
```

---

## ⚙️ Konfigurasi `.env` Lengkap

| Variable | Default | Deskripsi |
|---|---|---|
| `PROVIDER` | `grizzlysms` | Provider yang dipakai: `grizzlysms` atau `fivesim` |
| `GRIZZLY_API_KEY` | *(wajib jika provider=grizzlysms)* | API key dari dashboard GrizzlySMS |
| `FIVESIM_API_KEY` | *(wajib jika provider=fivesim)* | JWT token dari dashboard 5SIM |
| `GRIZZLY_PRODUCT` | `jio` | Produk di GrizzlySMS (default sudah benar) |
| `FIVESIM_PRODUCT` | `jiomart` | Produk di 5SIM (default sudah benar) |
| `MAX_PRICE` | `1.0` | Harga maks per nomor (USD). `0.5` = mode hemat |
| `CANCEL_DELAY_SECONDS` | `150` | Detik sebelum refund nomor gagal |
| `OTP_FAIL_DELAY_SECONDS` | `420` | Detik sebelum refund saat OTP gagal |
| `CONCURRENCY` | `2` | Jumlah worker paralel |
| `DB_PATH` | `results.db` | Path file database SQLite |
| `TG_BOT_TOKEN` | *(optional)* | Token bot Telegram dari @BotFather |
| `TG_CHAT_ID` | *(optional)* | Chat ID Telegram dari @userinfobot |

---

## 🔔 Setup Notifikasi Telegram

1. Buka Telegram, chat [@BotFather](https://t.me/BotFather)
2. Kirim `/newbot` → ikuti instruksi → dapat **Bot Token**
3. Chat [@userinfobot](https://t.me/userinfobot) → kirim `/start` → dapat **Chat ID**
4. Buka `.env`, uncomment & isi:

```env
TG_BOT_TOKEN=123456:ABCdefGHIjklMNOpqrsTUVwxyz
TG_CHAT_ID=987654321
```

Setiap kali link ditemukan, bot akan kirim pesan:

```
🎯 Google AI Pro link!

Nomor : +919876543210
Link :
https://serviceactivation.google.com/...
```

---

## 📁 Struktur Project

```
jiofarm/
├── jiofarm/                  # Package Python
│   ├── __init__.py
│   ├── __main__.py           # Entry point
│   ├── cli.py                # Typer CLI + Rich Live Dashboard
│   ├── config.py             # Load .env + dataclass config
│   ├── console.py            # Rich Console + Telegram helper
│   ├── shield.py             # DNS-over-HTTPS (Cloudflare)
│   ├── hunter.py             # Orchestrator hunt cycle (generic/provider-agnostic)
│   ├── grizzly/
│   │   ├── __init__.py
│   │   ├── client.py         # GrizzlySMS API client
│   │   └── refund.py         # Auto-refund worker
│   ├── fivesim/
│   │   ├── __init__.py
│   │   └── client.py         # 5SIM API client
│   ├── jio/
│   │   ├── __init__.py
│   │   ├── auth.py           # Jio OTP login
│   │   ├── check.py          # Validasi subscriber Jio
│   │   └── hunt.py           # Link hunting endpoints
│   └── storage/
│       ├── __init__.py
│       └── store.py          # SQLite hasil hunt
├── requirements.txt
├── pyproject.toml
├── .env.example
└── .gitignore
```

---

## 🧠 Cara Kerja

```
    [SMS Provider]            [Jio Selfcare]            [Google APIs]
    (Grizzly/5SIM/dll)             │                         │
         │                         │                         │
    1. sewa nomor ────────────► 2. kirim OTP                 │
         │                    3. terima OTP ◄───┐             │
         │                    4. validate OTP ──┘             │
         │                    5. login sukses ───────────► 6. hunt link
         │                                              7. link ketemu!
         │                         │                         │
    8. complete / refund ◄─────────┘                         │
```

Setiap worker menjalankan siklus ini secara paralel. Nomor yang gagal di-refund otomatis oleh `RefundWorker`.

**Refund logic:**
- **Bukan pelanggan Jio** → refund agresif (retry tiap 30 detik setelah 120s)
- **OTP nggak masuk** → refund setelah 420 detik (7 menit)
- **Gagal sebelum login** → refund setelah 150 detik
- **Login sukses** → dana dianggap terpakai (complete), tidak refund

---

## 🛡️ DNS Shield

Beberapa ISP (terutama di Indonesia) memblokir domain provider SMS via DNS. JioFarm punya **DNS-over-HTTPS shield** yang me-resolve domain lewat Cloudflare (1.1.1.1), bypass pemblokiran ISP.

Aktif otomatis tiap kali `run`.

---

## ❓ FAQ

**Q: Berapa biaya per nomor?**
A: Tergantung provider. GrizzlySMS Jio ~$0.20–$1.00. 5SIM ~$0.05. Pakai `--max-price 0.5` untuk mode hemat.

**Q: Kenapa login sukses tapi nggak dapat link?**
A: Nggak semua nomor Jio dapat promo Google AI Pro — ini pure RNG. Baca [§ Memilih Provider](#-memilih-provider---penting) untuk tips meningkatkan link rate.

**Q: Kenapa link rate saya rendah banget?**
A: Kemungkinan provider kamu punya nomor recycled (bekas dipakai hunter lain). **Coba cari provider yang lebih sepi peminat** — nomor fresh = chance lebih tinggi. Jangan cuma stuck di 1 provider.

**Q: Dana bisa hangus?**
A: Kalau login sukses tapi nggak ada link, dana tetap terpakai. Kalau gagal sebelum login, dana di-refund otomatis. Lihat refund logic di atas.

**Q: Aman nggak pakai API key di `.env`?**
A: `.env` sudah ada di `.gitignore` — tidak akan ke-commit ke Git. Jangan share file `.env` ke siapapun.

**Q: Bisa pakai provider selain GrizzlySMS?**
A: Bisa. JioFarm support multi-provider. Pilih `PROVIDER=fivesim` atau tambah provider sendiri. Lihat [§ Memilih Provider](#-memilih-provider---penting).

**Q: Kok 5SIM jiomart nggak bisa dipakai?**
A: Client 5SIM sudah siap, tapi API buy mereka untuk `jiomart` sering "no free phones" meskipun stok di web ada. Ini bug dari sisi 5SIM. Cek berkala siapa tahu sudah difix. Kalau sudah normal, tinggal ganti `PROVIDER=fivesim` di `.env`.

---

## 📜 License

MIT © 2024

---

<div align="center">

**🦁 Happy Hunting! — Dan ingat: provider yang bagus = hasil yang bagus.**

</div>