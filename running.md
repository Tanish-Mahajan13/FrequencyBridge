# Running FreqBridge Locally

This is the complete, step-by-step guide to getting the project running on
your machine. It's split into two parts:

- **[Do once](#do-once)** — setup you only need to do the first time (or after pulling changes that touch dependencies).
- **[Do every time](#do-every-time)** — the commands you run each session to actually use the project.

---

## Do Once

### 1. Clone the repo

```bash
git clone <repo-url>
cd freqbridge
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Install dependencies

Activate the environment first (see [Activating the virtual environment](#activating-the-virtual-environment) below), then:

```bash
pip install -r requirements.txt
```

This installs numpy, scipy, matplotlib, fastapi, uvicorn, pandas, plotly, google-genai, python-dotenv, and everything else the project needs. You only need to re-run this if `requirements.txt` changes (e.g. after pulling new commits).

Log persistence (`src/backend/log_store.py`) uses Python's built-in `sqlite3` module — nothing extra to install for that.

### 4. (Optional) Set up your Gemini API key

The live dashboard has a "Grid Analyst" panel that asks Gemini for a plain-English read on what's happening in the simulation. It's optional — without a key, the panel still works using built-in rule-based commentary (labeled "medium" confidence instead of "high").

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
cp .env.example .env
```

Open `.env` and paste your key in:
```
GEMINI_API_KEY=your-key-here
```

That's it — `.env` is loaded automatically every time the backend starts, no need to `export` it manually or repeat this per terminal session. `.env` is already in `.gitignore`, so your key won't accidentally get committed.

That's it for one-time setup. Everything below this line, you'll do every time you want to work on or demo the project.

---

## Do Every Time

### 1. Activate the virtual environment

You need to do this once per new terminal session, before running anything below.

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows:**
```bash
.venv\Scripts\activate
```

You'll know it worked because your terminal prompt will show `(.venv)` at the start of the line. Deactivate any time with `deactivate`.

### 2. Run whichever of these you need

All of these assume you're in the repo root with the venv activated. If you set up `.env` with your Gemini key in step 4 above, it'll be picked up automatically — nothing extra to do here.

**Run the test suite** — confirms nothing is broken:
```bash
python -m pytest tests/ -v
```
Expect `53 passed`.

**Run individual simulation scripts:**
```bash
# Phase 1 — validation spike (frequency ODE sanity check, writes data/validation_spike.png)
python scripts/run_validation_spike.py

# Phase 3 — auction scenario tests (prints trade results to terminal)
python scripts/run_auction_scenarios.py

# Phase 5 — full 24h simulation (market vs PID baseline, writes data/simulation_results.html)
python scripts/run_full_sim.py
```

You may see a line like:
```
[Live Weather] WARNING: Open-Meteo fetch failed (...). Falling back to default baselines...
```
This is expected if the weather API isn't reachable — it's a fallback, not an error. If your network can reach `api.open-meteo.com`, it'll fetch live data instead.

**Launch the live dashboard** (two terminals, both need the venv activated):

Terminal 1 — backend:
```bash
python -m uvicorn src.backend.api:app --host 0.0.0.0 --port 8000
```

Terminal 2 — frontend:
```bash
cd frontend
python -m http.server 3000
```

Then open **http://localhost:3000** in your browser.

---

## Log Persistence & Reset Behavior

`/reset` (the Reset button in the dashboard) rebuilds the simulation from scratch, but **it no longer clears the log panel**. Instead:

- The visible log panel keeps every prior entry and just adds a `[System] --- Simulation reset ---` marker, so you get one continuous log stream across resets instead of the panel going blank.
- Every log line is also written to a lightweight SQLite database at `data/logs.sqlite3`, which survives not just `/reset` but a full backend restart (stop and re-run uvicorn — the history is still there).
- Full persisted history (uncapped, unlike the rolling 100-entry panel) is available at `GET /logs/history?limit=500`.
- If the database can't be written to for some reason (disk issue, permissions), logging degrades gracefully — the live panel keeps working, you just lose the durable copy for that session. It won't crash the simulation. See `tests/test_log_store.py` for both the normal-persistence and failure-degradation cases.

`data/logs.sqlite3` is already covered by `.gitignore`'s `*.sqlite3` rule, so it won't get committed. Delete that file any time to start the persisted history over from scratch.

---

## Activating the Virtual Environment

Quick reference, since you'll be doing this a lot:

| Shell | Command |
|---|---|
| macOS/Linux (bash/zsh) | `source .venv/bin/activate` |
| Windows (cmd/PowerShell) | `.venv\Scripts\activate` |

If you close your terminal, the venv deactivates automatically — just reactivate next time. You do **not** need to reinstall dependencies each time, only re-activate.

---

## Tuning the Converter Flow Smoothing

If you're prepping a demo and want to adjust how "steady" the converter power looks during a crisis, edit `flow_smoothing_alpha` in `src/backend/runner.py` (`_create_sim()`), or in `src/sim/simulation_loop.py`'s `SimulationConfig` default:

- Lower (e.g. `0.15`) → steadier line, slower to react to a genuine step-change crisis.
- Higher (toward `1.0`) → more responsive, but noisier/jitterier — `1.0` disables smoothing entirely (raw passthrough).

No reinstall needed for this — just save the file and restart the backend (`Ctrl+C` then re-run the uvicorn command above).

---

## Troubleshooting

- **`ModuleNotFoundError`** — you probably forgot to activate the venv, or dependencies changed and you need to re-run `pip install -r requirements.txt`.
- **`externally-managed-environment` error during `pip install`** — you're installing outside a venv on a system with PEP 668 restrictions. Make sure you actually activated `.venv` first (see above); don't use `--break-system-packages` unless you specifically know you want a system-wide install.
- **Full sim / dashboard shows "Live Weather" fallback warning** — expected when `api.open-meteo.com` isn't reachable; the simulation still runs correctly on default baselines.
- **Port already in use (8000 or 3000)** — something else is already running there. Either stop it, or pass a different `--port` to uvicorn / `python -m http.server`.