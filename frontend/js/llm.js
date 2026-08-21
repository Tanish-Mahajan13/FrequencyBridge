// Grid Analyst panel — calls /llm/analyze periodically (auto trigger) and
// immediately on crisis-injection button clicks (crisis trigger), then
// renders the response into #llm-panel. Fails silently on network errors
// so a Gemini/network hiccup never breaks the rest of the dashboard.

const LLM_AUTO_INTERVAL_TICKS = 15; // ~15 real seconds, since dt_seconds=1
let lastLLMTick = -LLM_AUTO_INTERVAL_TICKS; // allow an immediate first call
let llmRequestInFlight = false;
let pendingCrisisTrigger = false;

function setLLMLoading(isLoading) {
    document.getElementById('llm-loading').style.display = isLoading ? 'inline' : 'none';
}

function renderLLMResult(data) {
    document.getElementById('llm-text').innerText = data.analysis;
    document.getElementById('llm-tick').innerText = `tick ${data.tick}`;

    const badge = document.getElementById('llm-confidence');
    badge.innerText = data.confidence;
    badge.className = 'badge ' + (data.confidence === 'high' ? 'high' : 'medium');
}

function callLLMAnalyze(state, trigger) {
    if (llmRequestInFlight) return;
    llmRequestInFlight = true;
    setLLMLoading(true);

    fetch(`${API_BASE}/llm/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: state, trigger: trigger })
    })
        .then(r => r.json())
        .then(data => {
            renderLLMResult(data);
        })
        .catch(() => {
            // Silently fail — don't break the dashboard. Leave whatever
            // text was already showing (or the initial placeholder).
        })
        .finally(() => {
            llmRequestInFlight = false;
            setLLMLoading(false);
        });
}

function maybeCallLLM(state) {
    if (!state || !state.kpis || !state.topology) return;

    // Crisis override — a shock button was just clicked, analyze immediately
    // (server-side cooldown for "crisis" trigger still applies, so this
    // can't be spammed even if the WS delivers several frames in a row).
    if (pendingCrisisTrigger) {
        pendingCrisisTrigger = false;
        lastLLMTick = state.tick;
        callLLMAnalyze(state, 'crisis');
        return;
    }

    // Regular polling cadence
    if (state.tick - lastLLMTick >= LLM_AUTO_INTERVAL_TICKS) {
        lastLLMTick = state.tick;
        callLLMAnalyze(state, 'auto');
    }
}

simStream.subscribe((state) => {
    maybeCallLLM(state);
});

// Trigger an immediate analysis on crisis injection clicks. Uses the next
// state frame that arrives over the WebSocket (rather than firing off the
// current stale state right at click time) so the analysis reflects the
// shock that was just injected.
['btn-cloud-shock', 'btn-east-shock', 'btn-wind-collapse'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) {
        btn.addEventListener('click', () => {
            pendingCrisisTrigger = true;
        });
    }
});