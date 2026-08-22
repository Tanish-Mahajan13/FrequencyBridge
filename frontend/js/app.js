const API_BASE = "http://localhost:8000";

// API Actions
async function postAction(endpoint) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`, { method: "POST" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        console.log(`Action ${endpoint} successful`);
    } catch (e) {
        console.error(`Failed to execute ${endpoint}:`, e);
    }
}

document.getElementById('btn-start').addEventListener('click', () => postAction('/start'));
document.getElementById('btn-pause').addEventListener('click', () => postAction('/pause'));
document.getElementById('btn-reset').addEventListener('click', () => postAction('/reset'));
document.getElementById('btn-cloud-shock').addEventListener('click', () => postAction('/inject/cloud'));
document.getElementById('btn-east-shock').addEventListener('click', () => postAction('/inject/east_shock'));
document.getElementById('btn-wind-collapse').addEventListener('click', () => postAction('/inject/wind'));
document.getElementById('btn-pid-mode').addEventListener('click', () => postAction('/switch/pid'));

// Format numbers
function fmtNum(val, decimals = 2) {
    return parseFloat(val).toFixed(decimals);
}

// UI Updating
let lastLogsSeq = -1;

simStream.subscribe((state) => {
    // 0. Status Indicator & Mode Button
    const statusInd = document.getElementById('status-indicator');
    if (state.running) {
        statusInd.textContent = '● LIVE';
        statusInd.style.color = 'var(--color-success)';
    } else {
        statusInd.textContent = '● PAUSED';
        statusInd.style.color = 'var(--color-warning)';
    }

    const pidBtn = document.getElementById('btn-pid-mode');
    if (state.mode === 'pid') {
        pidBtn.textContent = 'Switch Market';
        pidBtn.style.borderColor = 'var(--color-warning)';
        pidBtn.style.color = 'var(--color-warning)';
    } else {
        pidBtn.textContent = 'Switch PID';
        pidBtn.style.borderColor = '';
        pidBtn.style.color = '';
    }

    // 1. KPI Strip
    const eastFreq = document.getElementById('kpi-east-freq');
    const westFreq = document.getElementById('kpi-west-freq');
    const riskBox = document.getElementById('kpi-blackout-risk');

    eastFreq.textContent = `${fmtNum(state.kpis.east_freq)} Hz`;
    westFreq.textContent = `${fmtNum(state.kpis.west_freq)} Hz`;
    document.getElementById('kpi-converter-util').textContent = `${fmtNum(state.kpis.converter_utilization * 100, 1)}%`;
    document.getElementById('kpi-energy-traded').textContent = `${fmtNum(state.kpis.energy_traded_mwh, 1)}`;

    const riskPct = state.kpis.blackout_risk * 100;
    riskBox.textContent = `${fmtNum(riskPct, 0)}%`;

    // Risk Box Styling
    const riskContainer = riskBox.closest('.kpi-box');
    if (riskPct > 50) {
        riskContainer.style.borderColor = 'var(--color-danger)';
        riskBox.style.color = 'var(--color-danger)';
    } else if (riskPct > 10) {
        riskContainer.style.borderColor = 'var(--color-warning)';
        riskBox.style.color = 'var(--color-warning)';
    } else {
        riskContainer.style.borderColor = 'var(--color-success)';
        riskBox.style.color = 'var(--color-success)';
    }

    // Frequency color warnings
    eastFreq.style.color = Math.abs(state.kpis.east_freq - 50) > 0.1 ? 'var(--color-danger)' : 'var(--color-info)';
    westFreq.style.color = Math.abs(state.kpis.west_freq - 60) > 0.1 ? 'var(--color-danger)' : 'var(--color-info)';

    // 2. Terminals logs
    //
    // Rebuild the (small, <=20-line) tail window whenever logs_seq changes,
    // rather than trying to append-diff based on state.logs.length. That
    // array is always the last-20 window from the backend, so its length
    // permanently pins at 20 once more than 20 log lines have ever been
    // produced (which happens within the first ~20 seconds of any run) —
    // comparing lengths against a pinned value silently froze the panel
    // forever. logs_seq is a monotonic counter that's never ambiguous.
    const logsContainer = document.getElementById('logs-container');
    if (state.logs_seq !== undefined && state.logs_seq !== lastLogsSeq) {
        logsContainer.innerHTML = '';
        (state.logs || []).forEach(txt => {
            const row = document.createElement('div');
            row.className = 'log-entry';

            if (txt.includes('[Auction]')) row.classList.add('auction');
            else if (txt.includes('[Converter]')) row.classList.add('converter');
            else if (txt.includes('[Error]') || txt.includes('[Freq')) row.classList.add('warning');
            else row.classList.add('system');

            row.textContent = `> ${txt}`;
            logsContainer.appendChild(row);
        });
        logsContainer.scrollTop = logsContainer.scrollHeight;
        lastLogsSeq = state.logs_seq;
    }

    // 3. Agent Telemetry Table
    const telemetryBody = document.getElementById('telemetry-body');
    if (state.topology && state.topology.nodes) {
        telemetryBody.innerHTML = ''; // clear current
        state.topology.nodes.forEach(agent => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
            
            // Mode highlighting
            let modeStr = agent.mode.toUpperCase();
            let modeColor = agent.mode === 'survival' ? 'var(--color-warning)' : 'var(--color-success)';

            tr.innerHTML = `
                <td style="padding: 0.5rem; font-weight: bold; color: #E5E7EB;">${agent.id}</td>
                <td style="padding: 0.5rem; color: #9CA3AF;">${agent.region.toUpperCase()}</td>
                <td style="padding: 0.5rem; color: #38BDF8;">${fmtNum(agent.generation_mw)}</td>
                <td style="padding: 0.5rem; color: #F87171;">${fmtNum(agent.demand_mw)}</td>
                <td style="padding: 0.5rem; color: #8B5CF6; font-weight: bold;">${fmtNum(agent.battery_mwh)}</td>
                <td style="padding: 0.5rem; font-weight: bold; color: ${modeColor};">${modeStr}</td>
                <td style="padding: 0.5rem; color: #A78BFA;">${fmtNum(agent.forecast_cf * 100, 1)}%</td>
            `;
            telemetryBody.appendChild(tr);
        });
    }
    // 4. Live Auction Feed
const auctionBody = document.getElementById('auction-feed-body');
if (state.last_trades && state.last_trades.length > 0) {
    auctionBody.innerHTML = '';
    state.last_trades.forEach(trade => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
        const crossStyle = trade.cross_region 
            ? 'color: #F59E0B; font-weight: bold;' 
            : 'color: #6B7280;';
        tr.innerHTML = `
            <td style="padding:0.5rem; color:#F87171;">${trade.buyer}</td>
            <td style="padding:0.5rem; color:#38BDF8;">${trade.seller}</td>
            <td style="padding:0.5rem; color:#E5E7EB;">${trade.volume_mw}</td>
            <td style="padding:0.5rem; color:#A78BFA;">$${trade.price}</td>
            <td style="padding:0.5rem; ${crossStyle}">${trade.cross_region ? '⚡ YES' : 'No'}</td>
        `;
        auctionBody.appendChild(tr);
    });
}
});