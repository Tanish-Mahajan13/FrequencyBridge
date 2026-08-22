"""
Runner for the FreqBridge simulation.
Wraps the sequential FreqBridgeSimulation in an async loop for real-time frontend consumption.
"""

import asyncio
import time
from typing import Dict, Any, List

from src.sim.simulation_loop import FreqBridgeSimulation, SimulationConfig
from src.backend.log_store import LogStore


class SimulationRunner:
    def __init__(self):
        self.sim = self._create_sim()
        self.is_running = False
        self.dt_seconds = 1.0  # Speed of simulation: 1 real second = 1 tick (5 mins simulation)
        self.task = None
        self.logs: List[str] = []

        # Monotonically increasing counter, incremented on every add_log()
        # call and NEVER reset (not even by reset()). Exists because
        # `self.logs` sent to the frontend is capped to the last 20 entries
        # (see get_frontend_state) — once more than 20 total log lines have
        # ever been produced, `len(self.logs[-20:])` is permanently pinned
        # at 20. The frontend used to diff on that array's length to detect
        # "is there anything new," which silently froze forever once the
        # window filled up. This counter gives it something unambiguous to
        # compare against instead.
        self.log_seq = 0

        # Lightweight persistent log store (SQLite). Logs survive `/reset`
        # and even a full backend restart — the in-memory `self.logs` list
        # above is just a capped rolling window for fast API/WebSocket
        # responses; this is the durable record.
        self.log_store = LogStore()
        self.session_id = self.log_store.start_session()
        
    def _create_sim(self) -> FreqBridgeSimulation:
        config = SimulationConfig(
            controller_type="market",
            total_ticks=9999999  # run forever until reset
        )
        return FreqBridgeSimulation(config)

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.task = asyncio.create_task(self._loop())

    def pause(self):
        self.is_running = False
        if self.task is not None:
            self.task.cancel()
            self.task = None

    def reset(self):
        self.pause()
        self.sim = self._create_sim()

        # NOTE: we intentionally do NOT clear self.logs here. Previously
        # `/reset` wiped the entire visible log panel, losing the session's
        # history. Now: the rolling panel keeps going (still capped at 100
        # entries by add_log(), oldest entries drop off as normal), and a
        # reset just adds a clear marker into that same continuous stream.
        # The full, uncapped history is additionally persisted in
        # log_store's SQLite DB, so it survives even a full backend restart
        # (not just a reset) — see src/backend/log_store.py.
        self.session_id = self.log_store.start_session()
        self.add_log("[System] --- Simulation reset ---")

    def inject_cloud_shock(self):
        """Global shock - hits both sides."""
        self.sim.weather_gen_east.inject_shock(solar_shock=-1.0, wind_shock=-1.0)
        self.sim.weather_gen_west.inject_shock(solar_shock=-1.0, wind_shock=-1.0)
        self.add_log("[Weather] Global Cloud Shock injected!")

    def inject_east_shock(self):
        """East-only shock - West stays healthy, can rescue East via auction."""
        self.sim.weather_gen_east.solar_params.long_term_mean = 0.0
        self.sim.weather_gen_east.wind_params.long_term_mean = 0.0
        self.sim.weather_gen_east.solar_params.volatility = 0.0
        self.sim.weather_gen_east.wind_params.volatility = 0.0
        self.sim.weather_gen_east.inject_shock(solar_shock=-1.0, wind_shock=-1.0)
        self.add_log("[Weather] Tokyo Cloud Shock injected! East CF dropping. West stable.")

    def inject_wind_collapse(self):
        self.sim.weather_gen_east.solar_params.long_term_mean = 0.0
        self.sim.weather_gen_east.wind_params.long_term_mean = 0.0
        self.sim.weather_gen_east.solar_params.volatility = 0.0
        self.sim.weather_gen_east.wind_params.volatility = 0.0
        self.sim.weather_gen_east.inject_shock(solar_shock=-1.0, wind_shock=-1.0)
        
        self.sim.weather_gen_west.solar_params.long_term_mean = 0.0
        self.sim.weather_gen_west.wind_params.long_term_mean = 0.0
        self.sim.weather_gen_west.solar_params.volatility = 0.0
        self.sim.weather_gen_west.wind_params.volatility = 0.0
        self.sim.weather_gen_west.inject_shock(solar_shock=-1.0, wind_shock=-1.0)
        self.add_log("[Weather] Massive Wind Collapse injected! CF dropping.")

    def switch_pid(self):
        if self.sim.config.controller_type == "market":
            self.sim.config.controller_type = "pid"
            self.add_log("[System] Switched to PID Baseline control mode.")
        else:
            self.sim.config.controller_type = "market"
            self.add_log("[System] Switched to Market control mode.")

    def add_log(self, msg: str):
        self.logs.append(msg)
        if len(self.logs) > 100:
            self.logs.pop(0)
        self.log_seq += 1
        # Durable copy — uncapped, survives resets and backend restarts.
        # Never raises, so a storage hiccup can't break the sim loop.
        self.log_store.insert(self.session_id, self.sim.current_tick, msg)

    async def _loop(self):
        while self.is_running:
            # Execute step
            try:
                self.sim.step()
                self._generate_step_logs()
            except Exception as e:
                self.add_log(f"[Error] Simulation Step Error: {e}")
                self.is_running = False
                break
                
            await asyncio.sleep(self.dt_seconds)

    def _generate_step_logs(self):
        if len(self.sim.history) == 0:
            return
        last_state = self.sim.history[-1]
        
        # Log market
        if last_state["trades_count"] > 0:
            self.add_log(f"[Auction] Matched {last_state['trades_count']} trades. Vol: {last_state['volume_cleared_mw']:.1f}MW")
            
        # Log flow
        flow = last_state["hvdc_flow_mw"]
        if abs(flow) > 10:
            direction = "East->West" if flow > 0 else "West->East"
            self.add_log(f"[Converter] Transfer {direction} at {abs(flow):.1f}MW")

        # Log frequency deviation
        f_east = last_state["freq_east"]
        f_west = last_state["freq_west"]
        if abs(f_east - 50.0) > 0.05:
            self.add_log(f"[Freq East] Warning: {f_east:.2f}Hz")
        if abs(f_west - 60.0) > 0.05:
            self.add_log(f"[Freq West] Warning: {f_west:.2f}Hz")

    def get_frontend_state(self) -> Dict[str, Any]:
        """Provides the aggregated state required by the frontend dashboard."""
        
        if len(self.sim.history) == 0:
            last = {
                "freq_east": 50.0, "freq_west": 60.0,
                "cf_east": 0.4, "cf_west": 0.4,
                "price_east": 30.0, "price_west": 30.0,
                "hvdc_flow_mw": 0.0,
                "trades_count": 0, "volume_cleared_mw": 0.0
            }
        else:
            last = self.sim.history[-1]

        # Extract agent states for topology visualization
        agents_data = []
        for a in self.sim.agents:
            # We determine pseudo-status (Green/Yellow/Red/Purple)
            # if generation < demand -> deficit
            gen = a.current_generation_mw
            dem = a.current_demand_mw
            
            # Simple heuristic
            status = "Green"
            if gen < dem:
                status = "Red"
            elif gen < dem * 1.2:
                status = "Yellow"
                
            # If agent has a hedge flag (pseudo logic)
            if hasattr(a, 'risk_state') and getattr(a.risk_state, 'blackout_probability', 0) > 0.3:
                status = "Purple"

            # Get Operating Mode
            mode = getattr(a, 'mode', 'profit')

            # Get 90-min forecast
            w_gen = self.sim.weather_gen_east if a.params.region == "east" else self.sim.weather_gen_west
            forecast = w_gen.generate_forecast(90, self.sim.config.tick_length_minutes)
            avg_forecast_cf = sum((f.solar_cf + f.wind_cf) / 2.0 for f in forecast) / len(forecast) if forecast else 0.0

            agents_data.append({
                "id": a.params.id,
                "region": a.params.region,
                "generation_mw": gen,
                "demand_mw": dem,
                "status": status,
                "battery_mwh": a.battery_energy_mwh if hasattr(a, 'battery_energy_mwh') else 0.0,
                "mode": mode,
                "forecast_cf": avg_forecast_cf
            })

        # Calculate metrics over history
        history = self.sim.history
        total_energy_traded_mwh = sum(h.get("volume_cleared_mw", 0) * (self.sim.config.tick_length_minutes/60) for h in history)
        max_flow = self.sim.converter.params.capacity_mw
        utilization = abs(last["hvdc_flow_mw"]) / max_flow if max_flow > 0 else 0

        # Pseudo blackout risk (aggregate)
        red_agents = sum(1 for a in agents_data if a["status"] == "Red")
        blackout_risk = min(1.0, red_agents / len(agents_data)) if agents_data else 0.0
        
        # Each tick = 1 real second in the runner's async loop (dt_seconds = 1.0)
        rt = self.sim.recovery_time_ticks
        recovery_time = rt if rt is not None else 0.0
        
        return {
            "tick": self.sim.current_tick,
            "running": self.is_running,
            "mode": self.sim.config.controller_type,
            "kpis": {
                "east_freq": last["freq_east"],
                "west_freq": last["freq_west"],
                "converter_utilization": utilization,
                "energy_traded_mwh": total_energy_traded_mwh,
                "blackout_risk": blackout_risk,
                "recovery_time": recovery_time
            },
            "weather": {
                "solar_cf_east": last["cf_east"],  # Simple approximation
                "solar_cf_west": last["cf_west"],
                "wind_cf_east": last["cf_east"] * 0.9, # Assuming wind follows somewhat
                "wind_cf_west": last["cf_west"] * 0.9,
            },
            "market": {
                "price_east": last["price_east"] or 0.0,
                "price_west": last["price_west"] or 0.0,
            },
            "topology": {
                "converter": {
                    "flow_mw": last["hvdc_flow_mw"],
                    "utilization": utilization
                },
                "nodes": agents_data
            },
            "last_trades": self.sim.last_trades,
            "logs": self.logs[-20:], # Only send last 20 logs
            "logs_seq": self.log_seq, # Monotonic counter — never resets, never pins. Use THIS to detect "is there anything new," not len(logs).
            "history": {
                "freq_east": [h["freq_east"] for h in self.sim.history[-60:]],
                "freq_west": [h["freq_west"] for h in self.sim.history[-60:]],
                "price_east": [(h["price_east"] or 0.0) for h in self.sim.history[-60:]],
                "price_west": [(h["price_west"] or 0.0) for h in self.sim.history[-60:]],
                "hvdc_flow": [h["hvdc_flow_mw"] for h in self.sim.history[-60:]],
                "time": [h["tick"] for h in self.sim.history[-60:]]
            }
        }