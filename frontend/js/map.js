// map.js — Real-geography overlay of the FreqBridge grid topology on a Japan map.
// Pulls the same simStream websocket state that topology.js uses; purely additive,
// does not touch backend state shape or the existing canvas topology view.

const AGENT_COORDS = {
    "East_City":        [35.6762, 139.6503], // Tokyo Metro
    "East_Industrial":  [35.5309, 139.7029], // Kawasaki corridor
    "East_WindFarm":    [38.2688, 140.8694], // Tohoku
    "West_SolarFarm":   [32.7503, 130.7418], // Kyushu solar belt
    "West_Residential": [34.6937, 135.5023], // Osaka/Kobe
};
const HVDC_COORDS = [36.1667, 137.9667]; // Shin-Shinano frequency converter station, Nagano

const MAP_STATUS_COLORS = {
    "Green": "#22C55E",
    "Yellow": "#F59E0B",
    "Red": "#EF4444",
    "Purple": "#8B5CF6",
};
const CONVERTER_COLOR = "#38BDF8";

let freqBridgeMap = null;
let agentMarkers = {};   // id -> L.circleMarker
let agentLabels = {};    // id -> L.marker (divIcon label)
let flowLines = {};      // id -> { base: L.polyline, active: L.polyline }
let hvdcMarker = null;

function initJapanMap() {
    if (freqBridgeMap) return;

    freqBridgeMap = L.map('japan-map', {
        center: [36.5, 136.5],
        zoom: 6,
        zoomControl: false,
        attributionControl: true
    });
    window.freqBridgeMap = freqBridgeMap;

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(freqBridgeMap);

    // HVDC converter node — rectangle divIcon
    const hvdcIcon = L.divIcon({
        className: 'hvdc-marker',
        html: 'HVDC<br>—',
        iconSize: [50, 34],
        iconAnchor: [25, 17]
    });
    hvdcMarker = L.marker(HVDC_COORDS, { icon: hvdcIcon, zIndexOffset: 1000 }).addTo(freqBridgeMap);
    hvdcMarker.bindPopup('HVDC Converter (Shin-Shinano)');

    // Agent nodes: base wire line + animated flow overlay + circle marker + label
    Object.keys(AGENT_COORDS).forEach((id) => {
        const coord = AGENT_COORDS[id];

        const base = L.polyline([coord, HVDC_COORDS], {
            color: 'rgba(255,255,255,0.25)',
            weight: 2,
            interactive: false
        }).addTo(freqBridgeMap);

        const active = L.polyline([coord, HVDC_COORDS], {
            color: CONVERTER_COLOR,
            weight: 3,
            dashArray: '10, 10',
            interactive: false,
            opacity: 0
        }).addTo(freqBridgeMap);

        flowLines[id] = { base, active };

        const marker = L.circleMarker(coord, {
            radius: 10,
            color: '#fff',
            weight: 1,
            fillColor: MAP_STATUS_COLORS["Green"],
            fillOpacity: 0.9
        }).addTo(freqBridgeMap);
        marker.bindPopup(`Loading ${id}...`);
        agentMarkers[id] = marker;

        const label = L.marker(coord, {
            icon: L.divIcon({
                className: 'freqbridge-marker-label',
                html: id.replace('_', ' '),
                iconSize: [120, 16],
                iconAnchor: [-14, 8]
            }),
            interactive: false
        }).addTo(freqBridgeMap);
        agentLabels[id] = label;
    });

    // Give the flow-active class to the active polylines' SVG paths so the
    // CSS keyframe animation can drive stroke-dashoffset.
    Object.values(flowLines).forEach(({ active }) => {
        const el = active.getElement();
        if (el) el.classList.add('flow-line-active');
    });
}

function updateJapanMap(state) {
    if (!freqBridgeMap || !state || !state.topology) return;

    const nodes = state.topology.nodes || [];
    const converter = state.topology.converter || { flow_mw: 0, utilization: 0 };
    const flow = converter.flow_mw || 0;
    const util = converter.utilization || 0;

    // HVDC converter marker
    if (hvdcMarker) {
        hvdcMarker.setIcon(L.divIcon({
            className: 'hvdc-marker',
            html: `HVDC<br>${Math.abs(flow).toFixed(0)} MW`,
            iconSize: [50, 34],
            iconAnchor: [25, 17]
        }));
        hvdcMarker.setPopupContent(
            `<b>HVDC Converter</b><br>Flow: ${flow.toFixed(0)} MW<br>Utilization: ${(util * 100).toFixed(0)}%`
        );
        const el = hvdcMarker.getElement();
        if (el) {
            el.style.boxShadow = util > 0.1
                ? `0 0 ${8 + util * 20}px rgba(56, 189, 248, 0.9)`
                : '0 0 8px rgba(56, 189, 248, 0.4)';
        }
    }

    nodes.forEach((node) => {
        const marker = agentMarkers[node.id];
        if (!marker) return; // unknown id — coords not hardcoded for this agent

        const color = MAP_STATUS_COLORS[node.status] || MAP_STATUS_COLORS["Green"];
        const radius = Math.max(6, Math.min(30, node.generation_mw / 10));

        marker.setStyle({ fillColor: color, radius });
        marker.setPopupContent(
            `<b>${node.id}</b><br>` +
            `Gen: ${node.generation_mw.toFixed(0)} MW<br>` +
            `Demand: ${node.demand_mw.toFixed(0)} MW<br>` +
            `Battery: ${node.battery_mwh.toFixed(0)} MWh<br>` +
            `Mode: ${node.mode}`
        );

        // Flow line: active only if this node is exporting power to the converter.
        const line = flowLines[node.id];
        if (line) {
            const isEast = node.id.startsWith('East_');
            // flow_mw > 0 convention follows topology.js: positive = East -> West.
            const exporting = isEast ? flow > 0 : flow < 0;
            const active = exporting && Math.abs(flow) > 1;

            line.active.setStyle({
                opacity: active ? Math.min(1, 0.4 + util * 0.6) : 0,
                weight: Math.max(2, Math.min(8, Math.abs(flow) / 100))
            });
        }
    });
}

// Init once the DOM/leaflet is ready.
if (document.getElementById('japan-map')) {
    initJapanMap();
}

simStream.subscribe((state) => {
    if (!freqBridgeMap) return;
    updateJapanMap(state);
});