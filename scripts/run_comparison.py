"""
Runs FreqBridge vs PID side-by-side under identical East shock conditions.
Outputs a clean comparison plot saved to data/recovery_comparison.png
"""

import sys
import os
import copy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.sim.simulation_loop import FreqBridgeSimulation, SimulationConfig

SHOCK_TICK = 10       # inject shock at tick 10
TOTAL_TICKS = 60      # run for 60 ticks (~1 hour sim time)
BLACKOUT_THRESHOLD = 49.5  # Hz — below this is blackout territory for East

def run_scenario(controller_type: str):
    config = SimulationConfig(
        controller_type=controller_type,
        total_ticks=TOTAL_TICKS
    )
    sim = FreqBridgeSimulation(config)

    freq_east_history = []
    freq_west_history = []

    for tick in range(TOTAL_TICKS):
        if tick == SHOCK_TICK:
            # Inject East-only shock
            sim.weather_gen_east.solar_params.long_term_mean = 0.0
            sim.weather_gen_east.wind_params.long_term_mean = 0.0
            sim.weather_gen_east.solar_params.volatility = 0.0
            sim.weather_gen_east.wind_params.volatility = 0.0
            sim.weather_gen_east.inject_shock(solar_shock=-1.0, wind_shock=-1.0)

        sim.step()
        last = sim.history[-1]
        freq_east_history.append(last["freq_east"])
        freq_west_history.append(last["freq_west"])

    recovery_ticks = sim.recovery_time_ticks
    return freq_east_history, freq_west_history, recovery_ticks

print("Running Market scenario...")
mkt_east, mkt_west, mkt_recovery = run_scenario("market")

print("Running PID scenario...")
pid_east, pid_west, pid_recovery = run_scenario("pid")

ticks = list(range(TOTAL_TICKS))

# --- Plot ---
fig = plt.figure(figsize=(14, 5), facecolor="#0d1117")
gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35)

def style_ax(ax, title):
    ax.set_facecolor("#0d1117")
    ax.set_title(title, color="white", fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors="#888888")
    ax.xaxis.label.set_color("#888888")
    ax.yaxis.label.set_color("#888888")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    ax.set_xlabel("Simulation Tick", fontsize=10)
    ax.set_ylabel("East Grid Frequency (Hz)", fontsize=10)
    ax.axhline(y=BLACKOUT_THRESHOLD, color="#ff4444", linewidth=1,
               linestyle="--", alpha=0.7, label="Blackout Threshold (49.5Hz)")
    ax.axhline(y=50.0, color="#444444", linewidth=0.8, linestyle=":")
    ax.set_ylim(49.0, 50.3)
    ax.legend(fontsize=9, facecolor="#1a1a2e", labelcolor="white", 
              edgecolor="#333333")

# Left: FreqBridge
ax1 = fig.add_subplot(gs[0])
style_ax(ax1, "FreqBridge — Market Agent")
ax1.plot(ticks, mkt_east, color="#4fc3f7", linewidth=2, label="East Freq (Hz)")
if mkt_recovery is not None:
    ax1.annotate(f"Recovered in {mkt_recovery} ticks",
                xy=(SHOCK_TICK + mkt_recovery, 49.95),
                xytext=(SHOCK_TICK + mkt_recovery + 3, 49.85),
                arrowprops=dict(arrowstyle="->", color="#4fc3f7"),
                color="#4fc3f7", fontsize=9)
ax1.legend(fontsize=9, facecolor="#1a1a2e", labelcolor="white", edgecolor="#333333")

# Right: PID
ax2 = fig.add_subplot(gs[1])
style_ax(ax2, "PID Baseline — Reactive Control")
ax2.plot(ticks, pid_east, color="#ff7043", linewidth=2, label="East Freq (Hz)")
ax2.axhspan(49.0, BLACKOUT_THRESHOLD, alpha=0.08, color="#ff4444",
            label="Blackout Zone")
if pid_recovery is not None:
    ax2.annotate(f"Recovered in {pid_recovery} ticks",
                xy=(SHOCK_TICK + pid_recovery, 49.95),
                xytext=(SHOCK_TICK + pid_recovery + 3, 49.85),
                arrowprops=dict(arrowstyle="->", color="#ff7043"),
                color="#ff7043", fontsize=9)
ax2.legend(fontsize=9, facecolor="#1a1a2e", labelcolor="white", edgecolor="#333333")

fig.suptitle("FreqBridge vs PID: Crisis Recovery Under East Grid Shock",
             color="white", fontsize=15, fontweight="bold", y=1.02)

out_path = "data/recovery_comparison.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#0d1117")
print(f"Saved to {out_path}")
print(f"Market recovery: {mkt_recovery} ticks | PID recovery: {pid_recovery} ticks")