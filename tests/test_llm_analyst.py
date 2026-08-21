"""
Tests for GridAnalyst (src/backend/llm_analyst.py).

Focused on the parts that must never break the dashboard even when Gemini
is unavailable: prompt building against real state shape, and the
rule-based fallback path when GEMINI_API_KEY is missing.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend.llm_analyst import GridAnalyst
from src.backend.runner import SimulationRunner


def _sample_state(ticks=3):
    """Build a real frontend state dict by actually running the sim a few ticks."""
    runner = SimulationRunner()
    for _ in range(ticks):
        runner.sim.step()
    return runner.get_frontend_state()


class TestGridAnalystPrompt:
    def test_build_prompt_does_not_crash_on_real_state(self):
        state = _sample_state()
        analyst = GridAnalyst()
        prompt = analyst.build_prompt(state)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_build_prompt_includes_key_numbers(self):
        state = _sample_state()
        analyst = GridAnalyst()
        prompt = analyst.build_prompt(state)
        assert f"Tick {state['tick']}" in prompt
        assert "East frequency" in prompt
        assert "West frequency" in prompt

    def test_build_prompt_handles_no_trades(self):
        state = _sample_state()
        state["last_trades"] = []
        analyst = GridAnalyst()
        prompt = analyst.build_prompt(state)
        assert "No trades this tick" in prompt

    def test_build_prompt_handles_empty_logs(self):
        state = _sample_state()
        state["logs"] = []
        analyst = GridAnalyst()
        prompt = analyst.build_prompt(state)
        assert prompt  # just shouldn't crash


class TestGridAnalystFallback:
    def test_analyze_falls_back_without_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        state = _sample_state()
        analyst = GridAnalyst()
        result = analyst.analyze(state)

        assert result["confidence"] == "medium"
        assert result["tick"] == state["tick"]
        assert isinstance(result["analysis"], str)
        assert len(result["analysis"]) > 0

    def test_fallback_flags_high_blackout_risk_as_critical(self):
        state = _sample_state()
        state["kpis"]["blackout_risk"] = 0.9
        analyst = GridAnalyst()
        result = analyst._fallback_analysis(state)
        assert "CRITICAL" in result["analysis"]

    def test_fallback_reports_stable_grid(self):
        state = _sample_state()
        state["kpis"]["blackout_risk"] = 0.0
        state["kpis"]["east_freq"] = 50.0
        state["kpis"]["west_freq"] = 60.0
        analyst = GridAnalyst()
        result = analyst._fallback_analysis(state)
        assert "stable" in result["analysis"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])