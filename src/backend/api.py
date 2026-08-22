import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.backend.runner import SimulationRunner
from src.backend.llm_analyst import GridAnalyst

# Global single instance wrapper
runner = SimulationRunner()
analyst = GridAnalyst()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup
    yield
    # Teardown
    runner.pause()

app = FastAPI(title="FreqBridge API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/start")
async def start_sim():
    runner.start()
    return {"status": "started"}

@app.post("/pause")
async def pause_sim():
    runner.pause()
    return {"status": "paused"}

@app.post("/reset")
async def reset_sim():
    runner.reset()
    return {"status": "reset"}

@app.post("/inject/cloud")
async def inject_cloud():
    runner.inject_cloud_shock()
    return {"status": "cloud shock injected"}

@app.post("/inject/wind")
async def inject_wind():
    runner.inject_wind_collapse()
    return {"status": "wind shock injected"}

@app.post("/inject/east_shock")
async def inject_east_shock():
    runner.inject_east_shock()
    return {"status": "east cloud shock injected"}

@app.post("/switch/pid")
async def switch_pid():
    runner.switch_pid()
    return {"status": "switched to pid baseline"}

@app.get("/state")
async def get_state():
    return runner.get_frontend_state()

# Provide stub endpoints mapped to /state subsets for compatibility if needed
@app.get("/metrics")
async def get_metrics():
    return runner.get_frontend_state().get("kpis")

@app.get("/topology")
async def get_topology():
    return runner.get_frontend_state().get("topology")

@app.get("/logs")
async def get_logs():
    return {"logs": runner.logs}

@app.get("/logs/history")
async def get_logs_history(limit: int = 500):
    """
    Full persisted log history from the SQLite log store — survives
    resets AND backend restarts, unlike /logs (which only reflects the
    current rolling in-memory window). Returns [] if the store is
    unavailable rather than erroring.
    """
    return {
        "available": runner.log_store.is_available(),
        "logs": runner.log_store.get_all(limit=limit),
    }

# LLM GRID ANALYST
# Rate-limited so a busy dashboard (WebSocket pushes state at 2Hz) can't
# hammer the Gemini API. "auto" calls (frontend polling every ~15 ticks)
# use the full 15s cooldown; "crisis"/"user" triggers (button clicks) get a
# shorter cooldown so a demo moment feels responsive, but still can't be
# button-mashed into spamming the API.
_last_llm_call_time = {"auto": 0.0, "crisis": 0.0, "user": 0.0}
_llm_cache = None
_LLM_COOLDOWN_SECONDS = {"auto": 15.0, "crisis": 3.0, "user": 3.0}

@app.post("/llm/analyze")
async def llm_analyze(request: Request):
    global _llm_cache

    body = await request.json()
    trigger = body.get("trigger", "auto")
    if trigger not in _LLM_COOLDOWN_SECONDS:
        trigger = "auto"
    state = body.get("state") or runner.get_frontend_state()

    now = time.time()
    cooldown = _LLM_COOLDOWN_SECONDS[trigger]
    if now - _last_llm_call_time[trigger] < cooldown and _llm_cache is not None:
        return _llm_cache  # Return cached, don't hammer the API

    result = await asyncio.to_thread(analyst.analyze, state)
    _last_llm_call_time[trigger] = now
    _llm_cache = result
    return result

# WEBSOCKET
active_connections = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Send state at 2 Hz
            state_data = runner.get_frontend_state()
            await websocket.send_text(json.dumps(state_data))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception as e:
        if websocket in active_connections:
            active_connections.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.backend.api:app", host="0.0.0.0", port=8000, reload=True)