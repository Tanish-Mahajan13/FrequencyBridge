"""
Tests for the full FreqBridgeSimulation loop.

Covers the Bug 1 fix: the converter's requested flow is EMA-smoothed before
being handed to the converter, so a sustained regional deficit produces a
steady power transfer instead of a tick-to-tick stuttering value.
"""

import sys
import os
import statistics

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.sim.simulation_loop import FreqBridgeSimulation, SimulationConfig


def _run_east_deficit_scenario(flow_smoothing_alpha: float, ticks: int = 60, seed: int = 42):
    """Run a sustained east-side deficit and return the per-tick HVDC flow."""
    np.random.seed(seed)

    config = SimulationConfig(
        controller_type="market",
        total_ticks=ticks,
        flow_smoothing_alpha=flow_smoothing_alpha,
    )
    sim = FreqBridgeSimulation(config)

    # Kill east generation to force a sustained east-side deficit that
    # should, physically, converge to one steady West->East transfer.
    sim.weather_gen_east.solar_params.long_term_mean = 0.0
    sim.weather_gen_east.wind_params.long_term_mean = 0.0
    sim.weather_gen_east.solar_params.volatility = 0.0
    sim.weather_gen_east.wind_params.volatility = 0.0
    sim.weather_gen_east.inject_shock(solar_shock=-1.0, wind_shock=-1.0)

    flows = []
    for _ in range(ticks):
        sim.step()
        flows.append(sim.history[-1]["hvdc_flow_mw"])
    return flows


class TestFlowSmoothing:
    """Bug 1: converter flow should hold steady during a sustained deficit."""

    def test_smoothed_flow_reduces_tick_to_tick_jitter(self):
        """With smoothing enabled, tick-to-tick flow changes should be much
        smaller than the raw/unsmoothed (alpha=1.0) request."""
        raw_flows = _run_east_deficit_scenario(flow_smoothing_alpha=1.0)
        smoothed_flows = _run_east_deficit_scenario(flow_smoothing_alpha=0.25)

        # Skip the initial ramp-up window; compare steady-state jitter.
        raw_jitter = statistics.mean(
            abs(raw_flows[i] - raw_flows[i - 1]) for i in range(11, len(raw_flows))
        )
        smoothed_jitter = statistics.mean(
            abs(smoothed_flows[i] - smoothed_flows[i - 1]) for i in range(11, len(smoothed_flows))
        )

        assert smoothed_jitter < raw_jitter * 0.5, (
            f"Expected smoothing to cut tick-to-tick jitter by at least half "
            f"(raw={raw_jitter:.2f} MW, smoothed={smoothed_jitter:.2f} MW)"
        )

    def test_smoothing_preserves_average_delivered_power(self):
        """Smoothing should reduce noise, not systematically under/over-deliver
        power relative to what the unsmoothed system would have delivered."""
        raw_flows = _run_east_deficit_scenario(flow_smoothing_alpha=1.0)
        smoothed_flows = _run_east_deficit_scenario(flow_smoothing_alpha=0.25)

        raw_mean = statistics.mean(raw_flows[11:])
        smoothed_mean = statistics.mean(smoothed_flows[11:])

        # Means should be close (smoothing shifts phase/noise, not magnitude).
        assert abs(smoothed_mean - raw_mean) < 0.15 * abs(raw_mean)

    def test_default_config_has_smoothing_enabled(self):
        """The default SimulationConfig should smooth flow requests rather
        than pass raw per-tick auction output straight to the converter."""
        config = SimulationConfig()
        assert 0.0 < config.flow_smoothing_alpha < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])