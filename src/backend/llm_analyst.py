"""
GridAnalyst — Gemini-powered "Grid Analyst" commentary.

Builds a compact prompt from the current simulation state, calls the Gemini
API, validates the response, and falls back to deterministic rule-based
text if the call fails for any reason (no API key, rate limit, network
error, malformed/hedging response, etc).

Uses the current `google-genai` SDK (`pip install google-genai`), NOT the
deprecated `google-generativeai` package — that one stopped receiving
updates/bug fixes and prints a FutureWarning on import as of this writing.
See: https://github.com/google-gemini/deprecated-generative-ai-python
"""

import os
from typing import Any, Dict

from dotenv import load_dotenv

# Load variables from a .env file in the project root (if present) into the
# process environment. Safe no-op if the file doesn't exist — falls through
# to whatever's already in os.environ (e.g. a manually exported var).
load_dotenv()

from google import genai
from google.genai import types

# gemini-2.0-flash and flash-lite are on a retirement track; gemini-2.5-flash
# is the current fast/cheap default. Swap to "gemini-2.5-flash-lite" if you
# want even lower latency/cost and can live with a slightly weaker model.
GEMINI_MODEL = "gemini-2.5-flash"

MAX_OUTPUT_TOKENS = 150
TEMPERATURE = 0.3
MIN_VALID_RESPONSE_LEN = 20
HEDGE_PHRASES = ("i cannot", "i don't have", "as an ai")


class GridAnalyst:
    def __init__(self):
        # Lazy client creation: don't raise at import/startup time just
        # because GEMINI_API_KEY isn't set yet. If it's missing, `analyze()`
        # below will catch that and fall back to rule-based text instead of
        # taking down the whole backend/dashboard over an optional feature.
        self._client = None
        self.last_response: Dict[str, Any] = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY not set. Export it before starting the "
                    "backend, e.g.: export GEMINI_API_KEY='your-key-here'"
                )
            self._client = genai.Client(api_key=api_key)
        return self._client

    def build_prompt(self, state: dict) -> str:
        nodes = state["topology"]["nodes"]
        converter = state["topology"]["converter"]
        kpis = state["kpis"]
        trades = state.get("last_trades", [])
        logs = state.get("logs", [])

        # Summarise agent states compactly — don't dump the full JSON
        agent_lines = []
        for n in nodes:
            surplus = n["generation_mw"] - n["demand_mw"]
            sign = "+" if surplus >= 0 else ""
            agent_lines.append(
                f"  {n['id']} ({n['region'].upper()}): gen={n['generation_mw']:.0f}MW "
                f"demand={n['demand_mw']:.0f}MW net={sign}{surplus:.0f}MW "
                f"battery={n['battery_mwh']:.0f}MWh mode={n['mode']} status={n['status']}"
            )

        trade_lines = []
        for t in trades[:3]:  # max 3 trades
            cross = "via converter" if t.get("cross_region") else "local"
            price = t.get("price") or 0.0
            trade_lines.append(
                f"  {t['seller']}\u2192{t['buyer']} {t['volume_mw']:.1f}MW @ \u00a5{price:.1f} ({cross})"
            )

        return f"""You are a power systems analyst watching a real-time simulation of Japan's split electricity grid (50Hz East / 60Hz West).

CURRENT STATE (Tick {state['tick']}):
- East frequency: {kpis['east_freq']:.3f} Hz (nominal: 50.000)
- West frequency: {kpis['west_freq']:.3f} Hz (nominal: 60.000)
- HVDC converter flow: {converter['flow_mw']:.1f} MW ({'West\u2192East' if converter['flow_mw'] < 0 else 'East\u2192West'})
- Converter utilization: {kpis['converter_utilization']*100:.1f}%
- Grid stress indicator: {kpis['blackout_risk']*100:.0f}%
- Control mode: {state['mode'].upper()}

AGENT STATES:
{chr(10).join(agent_lines)}

RECENT TRADES:
{chr(10).join(trade_lines) if trade_lines else '  No trades this tick'}

RECENT SYSTEM LOGS:
{chr(10).join(logs[-5:]) if logs else '  None'}

In 3-4 sentences, explain:
1. What is happening in the grid RIGHT NOW (crisis, stable, recovering?)
2. What did the agents just decide and why?
3. Is the current situation improving or worsening?

Be specific with numbers. Use plain English. No bullet points. Max 80 words."""

    def analyze(self, state: dict) -> dict:
        try:
            client = self._get_client()
            prompt = self.build_prompt(state)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=TEMPERATURE,
                ),
            )
            text = (response.text or "").strip()

            # VALIDATE: reject if too short or contains obvious hallucination/hedging markers
            if len(text) < MIN_VALID_RESPONSE_LEN:
                raise ValueError("Response too short")
            if any(phrase in text.lower() for phrase in HEDGE_PHRASES):
                raise ValueError("Model refused or hedged")

            self.last_response = {
                "analysis": text,
                "tick": state["tick"],
                "confidence": "high",
            }
            return self.last_response

        except Exception as e:
            # FALLBACK: generate deterministic rule-based text from state.
            # This is what keeps the demo panel alive if Gemini is down,
            # rate-limited, or GEMINI_API_KEY was never configured.
            return self._fallback_analysis(state, error=str(e))

    def _fallback_analysis(self, state: dict, error: str = "") -> dict:
        kpis = state["kpis"]
        flow = state["topology"]["converter"]["flow_mw"]
        east_dev = abs(kpis["east_freq"] - 50.0)

        if kpis["blackout_risk"] > 0.5:
            text = (
                f"CRITICAL: Grid stress indicator at {kpis['blackout_risk']*100:.0f}%. "
                f"East frequency at {kpis['east_freq']:.2f}Hz. Agents switching to "
                f"survival mode and reserving battery buffers. Converter pushing "
                f"{abs(flow):.0f}MW {'West to East' if flow < 0 else 'East to West'}."
            )
        elif east_dev > 0.1:
            text = (
                f"Grid under stress. East frequency deviated to {kpis['east_freq']:.3f}Hz. "
                f"Auction engine routing {abs(flow):.0f}MW across HVDC converter to "
                f"stabilize. Market agents actively bidding."
            )
        else:
            text = (
                f"Grid stable. East: {kpis['east_freq']:.3f}Hz, West: {kpis['west_freq']:.3f}Hz. "
                f"Converter at {kpis['converter_utilization']*100:.0f}% utilization. "
                f"Agents in profit mode."
            )

        return {"analysis": text, "tick": state["tick"], "confidence": "medium"}