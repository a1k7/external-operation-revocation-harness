"use strict";

// ---------- Utilities ----------

async function api(path, options = {}) {
    const res = await fetch(`/api${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    const text = await res.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    if (!res.ok) {
        throw new Error(`${res.status}: ${body && body.detail ? body.detail : text}`);
    }
    return body;
}

function el(sel) { return document.querySelector(sel); }

// Helper to convert backend UTC ISO string to local time
function formatTime(isoString) {
    if (!isoString) return "—";
    try {
        const date = new Date(isoString);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) {
        return isoString;
    }
}

function pillForOutcome(outcome) {
    if (!outcome) return '<span class="pill neutral">not dispatched</span>';
    if (outcome === "COMPLETION_CONFIRMED")
        return `<span class="pill bad">${outcome}</span>`;
    if (outcome === "CANCELLATION_CONFIRMED")
        return `<span class="pill good">${outcome}</span>`;
    if (outcome === "CANCELLATION_ACKNOWLEDGED" || outcome === "CANCELLATION_REQUESTED")
        return `<span class="pill warn">${outcome}</span>`;
    if (outcome === "OUTCOME_UNKNOWN")
        return `<span class="pill unknown">${outcome}</span>`;
    return `<span class="pill neutral">${outcome}</span>`;
}

function pillForAuthStatus(status) {
    if (!status) return '<span class="pill neutral">—</span>';
    if (status === "GRANTED") return `<span class="pill good">${status}</span>`;
    return `<span class="pill bad">${status}</span>`;
}

function pillForDispatch(status) {
    if (!status) return '<span class="pill neutral">—</span>';
    if (status === "DISPATCHED") return `<span class="pill good">${status}</span>`;
    if (status === "BLOCKED_REVOKED") return `<span class="pill bad">${status}</span>`;
    if (status === "DUPLICATE") return `<span class="pill warn">${status}</span>`;
    return `<span class="pill neutral">${status}</span>`;
}

// ---------- Scenario buttons ----------

async function loadScenarioButtons() {
    try {
        const scenarios = await api("/scenarios");
        const container = el("#scenario-buttons");
        container.innerHTML = "";
        scenarios.forEach((item, index) => {
            const key = item.key || `scenario_${index + 1}`;
            const title = item.title || "Run Scenario";
            
            const btn = document.createElement("button");
            btn.innerHTML = `<strong>${String(key).replace("_", " ").toUpperCase()}</strong><br/>${String(title)}`;
            btn.addEventListener("click", async () => {
                el("#scenario-result").textContent = `Running ${key}…`;
                try {
                    const result = await api("/scenarios/run", {
                        method: "POST",
                        body: JSON.stringify({ scenario: key }),
                    });
                    el("#scenario-result").textContent = JSON.stringify(result, null, 2);
                    await refreshAll();
                } catch (err) {
                    el("#scenario-result").textContent = `Error: ${err.message}`;
                }
            });
            container.appendChild(btn);
        });
    } catch (err) {
        el("#scenario-result").textContent = `Failed to load scenarios: ${err.message}`;
    }
}

// ---------- Manual flow ----------

async function refreshAll() {
    await refreshOperations();
    await refreshEvidence();
    await refreshChain();
}

async function refreshOperations() {
    const ops = await api("/operations");
    const tbody = el("#ops-table tbody");
    tbody.innerHTML = "";
    ops.slice().reverse().forEach((op) => {
        const tr = document.createElement("tr");
        const cancelled =
            op.cancellation_rejected_reason
                ? `<span class="pill bad">rejected: ${op.cancellation_rejected_reason}</span>`
                : op.cancellation_acknowledged
                ? `<span class="pill warn">acknowledged</span>`
                : op.cancellation_requested
                ? `<span class="pill warn">requested</span>`
                : `<span class="pill neutral">none</span>`;
        
        // Format timestamps to local time here
        const localDispatched = formatTime(op.dispatched_at);
        const localRevoked = formatTime(op.authorization_revoked_at);

        tr.innerHTML = `
            <td class="mono">${op.operation_uid}</td>
            <td>${op.authorization_id}</td>
            <td>${pillForAuthStatus(op.authorization_status)}</td>
            <td>${op.authorization_version_used}</td>
            <td class="mono">${localDispatched}</td>
            <td class="mono">${localRevoked}</td>
            <td>${cancelled}</td>
            <td>${op.dispatch_status === "BLOCKED_REVOKED"
                ? pillForDispatch(op.dispatch_status)
                : (op.receiver_state || "—")}</td>
            <td>${pillForOutcome(op.verified_outcome)}</td>
        `;
        tr.style.cursor = "pointer";
        tr.addEventListener("click", () => {
            el("#verify-op").value = op.operation_uid;
            el("#cancel-op").value = op.operation_uid;
            showEvidenceFor(op.operation_uid);
        });
        tbody.appendChild(tr);
    });
}

async function refreshEvidence() {
    const events = await api("/evidence");
    const feed = el("#evidence-feed");
    feed.innerHTML = "";
    events.slice().reverse().slice(0, 100).forEach((e) => {
        const div = document.createElement("div");
        div.className = "event";
        const payload = JSON.stringify(e.payload);
        const localTime = formatTime(e.occurred_at);
        
        div.innerHTML = `
            <div class="time">${localTime}</div>
            <div class="type">${e.event_type}<br/><span style="color:var(--muted);font-weight:400">${e.subject_id.slice(0, 24)}</span></div>
            <div class="payload">${payload}</div>
        `;
        feed.appendChild(div);
    });
}

async function showEvidenceFor(operationUid) {
    const events = await api(`/operations/${encodeURIComponent(operationUid)}/evidence`);
    const feed = el("#evidence-feed");
    feed.innerHTML = "";
    events.slice().reverse().forEach((e) => {
        const div = document.createElement("div");
        div.className = "event";
        const localTime = formatTime(e.occurred_at);
        
        div.innerHTML = `
            <div class="time">${localTime}</div>
            <div class="type">${e.event_type}<br/><span style="color:var(--muted);font-weight:400">${e.subject_id.slice(0, 24)}</span></div>
            <div class="payload">${JSON.stringify(e.payload)}</div>
        `;
        feed.appendChild(div);
    });
}

async function refreshChain() {
    const status = await api("/evidence/verify");
    const elChain = el("#chain-status");
    if (status.intact) {
        elChain.innerHTML = `Ledger: <span class="pill good">intact</span> · ${status.total_events} events`;
    } else {
        elChain.innerHTML = `Ledger: <span class="pill bad">TAMPERED</span> at ${status.broken_at_event_uid}`;
    }
}

// ---------- Manual buttons ----------

el("#btn-grant").addEventListener("click", async () => {
    try {
        const body = {
            agent_id: el("#grant-agent").value,
            resource: el("#grant-resource").value,
        };
        const out = await api("/authorizations", {
            method: "POST",
            body: JSON.stringify(body),
        });
        el("#grant-out").textContent = `authorization_id=${out.id} version=${out.version}`;
        el("#dispatch-auth").value = out.id;
        el("#revoke-auth").value = out.id;
        await refreshAll();
    } catch (err) {
        el("#grant-out").textContent = `Error: ${err.message}`;
    }
});

el("#btn-dispatch").addEventListener("click", async () => {
    try {
        const body = {
            authorization_id: Number(el("#dispatch-auth").value),
            idempotency_key: el("#dispatch-key").value,
            amount_cents: Number(el("#dispatch-amount").value),
            force_inconclusive: el("#dispatch-inconcl").checked,
            simulated_settle_seconds: 600,
        };
        const out = await api("/operations/dispatch", {
            method: "POST",
            body: JSON.stringify(body),
        });
        el("#dispatch-out").textContent =
            `uid=${out.operation_uid} status=${out.dispatch_status}`;
        el("#cancel-op").value = out.operation_uid;
        el("#verify-op").value = out.operation_uid;
        await refreshAll();
    } catch (err) {
        el("#dispatch-out").textContent = `Error: ${err.message}`;
    }
});

el("#btn-revoke").addEventListener("click", async () => {
    try {
        const body = { reason: el("#revoke-reason").value };
        const out = await api(
            `/authorizations/${encodeURIComponent(el("#revoke-auth").value)}/revoke`,
            { method: "POST", body: JSON.stringify(body) },
        );
        el("#revoke-out").textContent =
            `auth ${out.id} → ${out.status} (v${out.version})`;
        await refreshAll();
    } catch (err) {
        el("#revoke-out").textContent = `Error: ${err.message}`;
    }
});

el("#btn-cancel").addEventListener("click", async () => {
    try {
        const out = await api(
            `/operations/${encodeURIComponent(el("#cancel-op").value)}/cancel`,
            { method: "POST", body: JSON.stringify({ reason: "manual cancel" }) },
        );
        el("#revoke-out").textContent =
            `receiver=${out.receiver_state} ack=${out.cancellation_acknowledged} rejected=${out.cancellation_rejected_reason || "no"}`;
        await refreshAll();
    } catch (err) {
        el("#revoke-out").textContent = `Error: ${err.message}`;
    }
});

el("#btn-advance").addEventListener("click", async () => {
    try {
        const uid = el("#verify-op").value;
        await api(`/operations/${encodeURIComponent(uid)}/advance?seconds=300`, {
            method: "POST",
        });
        await refreshAll();
    } catch (err) {
        el("#verify-out").textContent = `Error: ${err.message}`;
    }
});

el("#btn-verify").addEventListener("click", async () => {
    try {
        const out = await api(
            `/operations/${encodeURIComponent(el("#verify-op").value)}/verify`,
            { method: "POST" },
        );
        el("#verify-out").textContent =
            `outcome=${out.verified_outcome} receiver=${out.receiver_state_observed} — ${out.detail}`;
        await refreshAll();
    } catch (err) {
        el("#verify-out").textContent = `Error: ${err.message}`;
    }
});

// ---------- Boot ----------

loadScenarioButtons().then(refreshAll).catch((err) => {
    el("#scenario-result").textContent = `Boot error: ${err.message}`;
});

// Light polling so the dashboard reflects simulated-time transitions.
setInterval(refreshAll, 5000);