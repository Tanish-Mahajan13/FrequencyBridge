# FreqBridge

**Autonomous Multi-Agent Energy Arbitrage Engine for Japan's Split Grid**

FreqBridge is a decentralized multi-agent system that eliminates the *decision-latency* bottleneck around Japan's fixed HVDC converter capacity between the eastern (50 Hz) and western (60 Hz) grids. Each microgrid operates as an autonomous agent — monitoring generation vs. demand, calculating break-even prices, executing trades through a double auction, hedging against weather volatility, and prioritizing grid survival over profit when blackout probability crosses a threshold.

---

## Quick Start

> **Full step-by-step instructions (including what to run once vs. every time) are in [running.md](running.md).** This section is the short version.

### Prerequisites
- Python 3.10+
- pip

### Setup

```bash
# Clone the repo
git clone <repo-url>
cd freqbridge

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

```bash
# Run validation spike (Phase 1)
python scripts/run_validation_spike.py

# Run auction scenario tests (Phase 3)
python scripts/run_auction_scenarios.py

# Run full 24h simulation (Phase 5)
python scripts/run_full_sim.py

# Launch API Backend
python -m uvicorn src.backend.api:app --host 0.0.0.0 --port 8000

# Launch Frontend UI (in a new terminal)
cd frontend
python -m http.server 3000
```

### Tests

```bash
python -m pytest tests/ -v
```

---

## Architecture

```
src/
├── physics/          # Frequency ODE, weather generator
├── grid/             # Converter model, network topology
├── agents/           # Microgrid agents, hedging logic
├── market/           # Double auction engine, PID baseline
├── sim/              # Unified simulation loop
├── backend/          # FastAPI backend server
└── frontend/         # Vanilla HTML/CSS/JS dashboard
```

See [docs/architecture.md](docs/architecture.md) for detailed system design.

---

## Demo Scenes

1. **Normal State** — 5 microgrids live, all green, converter idle, prices flat
2. **Inject Crisis** — Cloud cover event triggers east-side deficit, auction clears, converter routes power
3. **Near Blackout Hedge** — Wind death predicted, west agents autonomously switch to survival mode
4. **Comparison** — FreqBridge recovers in ~12s vs PID baseline at ~47s

---

## Key Parameters

| Parameter | Value | Note |
|-----------|-------|------|
| Converter capacity | 1200 MW | Fixed physical constraint (1.2GW) |
| Transmission loss | 2% | Applied to cross-region trades |
| Hedge trigger | 70% P(blackout) | Demo-tuned threshold for SURVIVAL mode |
| Tick duration | 5m grid time | Configurable in settings.toml |
| Flow smoothing (`flow_smoothing_alpha`) | 0.25 | EMA smoothing on requested converter flow, `SimulationConfig` in `src/sim/simulation_loop.py`. Lower = steadier/slower to react, higher (toward 1.0) = raw/noisier. Tune per demo scene in `src/backend/runner.py`'s `_create_sim()`. |

Live weather (`src/physics/live_weather.py`) fetches current cloud cover / wind from Open-Meteo for Tokyo and Osaka on simulation start. If that API is unreachable (offline, rate-limited, blocked), it falls back to fixed default capacity factors and logs a warning instead of crashing.

---
## Validation

The frequency ODE was validated against a synthetic disturbance spike — a -0.1 pu generation loss on the East side produces the expected under-frequency nadir and recovery curve. See `data/validation_spike.png`.

---

## Grid Analyst Panel (Gemini)

The live dashboard includes a "Grid Analyst" panel (top of the page) that periodically asks Gemini for a plain-English read on what's happening in the simulation — e.g. "East is in deficit, agents are routing 44MW West→East via the converter, frequency is recovering." It updates automatically every ~15 ticks and immediately on crisis-injection button clicks.

- **Optional feature** — no `GEMINI_API_KEY`? The panel still works, just with built-in rule-based commentary instead of Gemini (shown as "medium" confidence vs "high"). Set it up via `.env` (see [running.md](running.md)) — copy `.env.example` to `.env` and paste your key in, no manual `export` needed.
- New endpoint: `POST /llm/analyze` (`src/backend/api.py`), rate-limited (15s cooldown for auto-polling, 3s for crisis/user-triggered calls) and cached so it can't hammer the Gemini API.
- Analyst logic lives in `src/backend/llm_analyst.py`. Uses the current `google-genai` SDK — not the deprecated `google-generativeai` package.

## Persistent Session Logs

`/reset` no longer wipes the log panel. It keeps the running log history and just adds a `[System] --- Simulation reset ---` marker, so a demo's log trail reads as one continuous session. Every log line is also durably persisted to a lightweight SQLite database (`data/logs.sqlite3`, stdlib-only, no extra dependency) via `src/backend/log_store.py` — this survives a full backend restart, not just a reset. Full uncapped history: `GET /logs/history`. If the database can't be written to, logging degrades to a safe no-op instead of crashing the sim — see `tests/test_log_store.py` for both cases.

## Recent Fixes

- **Converter flow stuttering (fixed):** the double auction re-clears from scratch every tick off that tick's instantaneous bids/asks, so during a sustained one-sided deficit the requested converter flow used to bounce tick-to-tick instead of holding steady (weather noise → generation noise → bid volume noise → requested-flow noise). Fixed by EMA-smoothing the requested flow (`flow_smoothing_alpha` in `SimulationConfig`, `src/sim/simulation_loop.py`) before it's handed to the converter. Cuts tick-to-tick jitter by ~4x in testing without changing average delivered power. Regression test: `tests/test_simulation_loop.py`.
- **Full-sim crash on network failure (fixed):** `scripts/run_full_sim.py` used to hard-crash if `api.open-meteo.com` was unreachable. `src/physics/live_weather.py` now falls back to fixed default capacity factors and logs a warning instead.
- **Missing dependency (fixed):** `plotly`, used by `scripts/run_full_sim.py` to generate the comparison HTML, is now listed in `requirements.txt`.
- **Missing dependency (fixed):** `python-dotenv`, required by `src/backend/llm_analyst.py` at import time, was missing from `requirements.txt` — a fresh `pip install` would install successfully but then crash immediately on starting the backend or running `pytest`. Now listed.

## License

MIT