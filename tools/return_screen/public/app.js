/* app.js — the return screen. Vanilla JS, no dependencies.
   Everything rendered comes from the server's JSON; nothing is invented here. */

const $ = (id) => document.getElementById(id);
const fmtT = (iso) => (iso ? iso.slice(11, 16) + "Z" : "—");
const fmtD = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") + "Z" : "—");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let OVERVIEW = null;
let PENDING_COUNT = 0;
let REWIND_POINT = null; // {at_epoch, at}
const MARK_STYLE = {
  "drift.hard":      { color: "#a02c2c", row: 0, label: "drift alarm (hard)" },
  "drift.tier":      { color: "#b3541e", row: 0, label: "drift alarm (tier)" },
  "drift.soft":      { color: "#c8a24a", row: 0, label: "drift alarm (soft)" },
  "skill.admitted":  { color: "#3c6e47", row: 1, label: "skill admitted (authored)" },
  "skill.retired":   { color: "#7a7466", row: 1, label: "skill retired (superseded)" },
  "judge.refusing":  { color: "#a02c2c", row: 0, label: "the judge began refusing" },
  "human.present":   { color: "#35597a", row: 2, label: "a human was present" },
  "visit.opened":    { color: "#35597a", row: 2, label: "this screen was opened" },
};
const CHARACTER_ACTORS = ["Kite", "Sprout", "Pebble", "Timber"];
const ALL_ACTORS = [...CHARACTER_ACTORS, "judge@d1:d1-2B", "seed", "mediator"];
const ALL_KINDS = ["tile.played", "judge.verdict", "tile.authored", "tile.retired"];

async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || res.status);
  return body;
}

/* ------------------------------------------------------------------ page */

async function load(human) {
  const ov = await api("/api/overview" + (human ? "?human=" + encodeURIComponent(human) : ""));
  OVERVIEW = ov;
  renderWho();
  renderLetter(ov.letter);
  renderThreshold(ov);
  renderScrubber(ov);
  renderLanes(ov.lanes);
  renderThread(ov);
  renderUndone(ov);
  $("ledger-line").textContent =
    `ledger: ${ov.span.rows} rows · ${ov.span.first_at} → ${ov.span.last_at} · ${ov.span.hours} h · read-only`;
  $("server-line").textContent = `folded ${ov.generated_at}`;
  await loadPrecedents();
  renderNext(ov);
}

function renderWho() {
  const sel = $("human-select");
  sel.innerHTML = "";
  const names = new Set(OVERVIEW.humans.map((h) => h.name));
  if (!names.has("Casey")) names.add("Casey");
  for (const n of names) {
    const opt = document.createElement("option");
    opt.value = n; opt.textContent = n;
    if (n === OVERVIEW.human) opt.selected = true;
    sel.appendChild(opt);
  }
  const sinceSrc = OVERVIEW.humans.find((h) => h.name === OVERVIEW.human);
  $("since-line").textContent =
    `last seen ${fmtD(OVERVIEW.since)}` +
    (sinceSrc ? ` (${sinceSrc.source})` : " (no visit recorded — showing the whole ledger)");
}

function renderLetter(letter) {
  $("letter-body").innerHTML = letter.paragraphs.map((p) => `<p>${esc(p)}</p>`).join("");
  $("letter-words").textContent = `${letter.word_count} words`;
  $("letter-question").textContent = letter.question;
  $("letter-receipts").querySelector("div").textContent = letter.receipts.join("\n");
}

function renderThreshold(ov) {
  const t = ov.threshold;
  const items = [
    ["plays", t.plays], ["verdicts", t.verdicts], ["refused", t.refused],
    ["skills authored", t.authored], ["skills retired", t.retired],
    ["drift alarms", t.drift_alarms], ["plays beside a human", t.plays_while_human_present],
  ];
  const mins = (Date.parse(ov.span.last_at) / 1000 - ov.since_epoch) / 60;
  const short = isFinite(mins) && mins < 10;
  const note = short
    ? `<p class="hint">your window is only ${Math.max(Math.round(mins), 0)} minute${Math.round(mins) === 1 ? "" : "s"} — you were here moments ago.
       The counters cover only that window; the ledger below holds ${ov.span.rows} rows over ${ov.span.hours} h.</p>`
    : "";
  $("threshold-counters").innerHTML = note + items.map(([k, v]) =>
    `<div class="counter"><b>${v ?? 0}</b><span>${k}</span></div>`).join("");

  const hourly = ov.hourly;
  const svg = $("hourly");
  if (!hourly.length) { svg.innerHTML = ""; return; }
  const W = 640, H = 80, max = Math.max(...hourly.map((h) => h.plays), 1);
  const bw = W / hourly.length;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = hourly.map((h, i) => {
    const bh = Math.round((h.plays / max) * (H - 22));
    return `<rect x="${(i * bw + 1).toFixed(1)}" y="${H - 14 - bh}" width="${Math.max(bw - 2, 1).toFixed(1)}" height="${bh}"><title>${esc(h.hour)} — ${h.plays} plays</title></rect>`;
  }).join("") +
    hourly.map((h, i) => (i % Math.ceil(hourly.length / 8) === 0)
      ? `<text x="${(i * bw).toFixed(0)}" y="${H - 3}">${fmtT(h.hour)}</text>` : "").join("");
}

/* ------------------------------------------------------------- scrubber */

function timeX(ov, epoch, W) {
  const t0 = ov.since_epoch, t1 = Date.parse(ov.span.last_at) / 1000;
  const span = Math.max(t1 - t0, 1);
  return ((epoch - t0) / span) * W;
}

function renderScrubber(ov) {
  const svg = $("scrubber");
  const W = 1000, H = 130;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const rows = { 0: 34, 1: 64, 2: 94 };
  const t1 = Date.parse(ov.span.last_at) / 1000;

  let out = "";
  // background bands: refusal + presence, full height
  for (const seg of ov.refusals || []) {
    const x0 = timeX(ov, Date.parse(seg.start) / 1000, W);
    const x1 = timeX(ov, Math.min(Date.parse(seg.end) / 1000, t1), W);
    if (x1 < 0 || x0 > W) continue;
    out += `<rect x="${x0.toFixed(1)}" y="10" width="${Math.max(x1 - x0, 2).toFixed(1)}" height="104" fill="#a02c2c" opacity="0.10"><title>the judge refused ${seg.refusals} verdicts (${esc(seg.start)} → ${esc(seg.end)})</title></rect>`;
  }
  // the axis
  out += `<line x1="0" y1="118" x2="${W}" y2="118" stroke="#d8d2c4" stroke-width="1"/>`;
  // the last-seen marker at x=0
  out += `<line x1="0" y1="8" x2="0" y2="124" stroke="#35597a" stroke-width="2"/><text x="4" y="18" font-size="10" fill="#35597a">last seen ${fmtT(ov.since)}</text>`;
  // hour ticks
  const t0 = ov.since_epoch, hours = Math.max((t1 - t0) / 3600, 1);
  const stepH = hours > 48 ? 12 : hours > 12 ? 4 : 1;
  for (let e = Math.ceil(t0 / 3600) * 3600; e < t1; e += stepH * 3600) {
    const x = timeX(ov, e, W);
    out += `<line x1="${x.toFixed(1)}" y1="118" x2="${x.toFixed(1)}" y2="123" stroke="#d8d2c4"/>` +
      `<text x="${(x + 2).toFixed(1)}" y="112" font-size="9" fill="#7a7466">${new Date(e * 1000).toISOString().slice(11, 16)}</text>`;
  }
  // the marks
  for (const m of ov.marks) {
    const st = MARK_STYLE[m.kind];
    if (!st) continue;
    const x = timeX(ov, m.at_epoch, W);
    if (x < -4 || x > W + 4) continue;
    const y = rows[st.row];
    out += `<g class="mark" data-at="${m.at_epoch}" data-seq="${m.seq ?? ""}">` +
      `<line x1="${x.toFixed(1)}" y1="${y - 8}" x2="${x.toFixed(1)}" y2="${y + 8}" stroke="${st.color}" stroke-width="${m.kind.startsWith("drift.hard") ? 4 : m.kind === "judge.refusing" ? 4 : 2}">` +
      `<title>${esc(st.label)} — ${esc(m.at)}${m.reason ? ": " + esc(m.reason) : ""}</title></line>` +
      `<circle cx="${x.toFixed(1)}" cy="${y}" r="7" fill="transparent"/></g>`;
  }
  // rewind point marker (kept across renders)
  if (REWIND_POINT) {
    const x = timeX(ov, REWIND_POINT.at_epoch, W);
    out += `<line x1="${x.toFixed(1)}" y1="4" x2="${x.toFixed(1)}" y2="126" stroke="#b3541e" stroke-width="2" stroke-dasharray="5 3"/><text x="${(x + 3).toFixed(1)}" y="30" font-size="10" fill="#b3541e">rewind point</text>`;
  }
  svg.innerHTML = out;

  // legend
  $("scrubber-legend").innerHTML = Object.entries(MARK_STYLE)
    .map(([k, st]) => `<span><i style="background:${st.color}"></i>${st.label}</span>`).join("");

  // actor lanes under the same axis, as density bursts
  const lanes = $("scrubber-lanes");
  const t1b = t1, t0b = ov.since_epoch;
  const burst = {};
  for (const b of ov.hourly) {
    const he = b.hour_epoch;
    for (const [actor, n] of Object.entries(b.by_agent || {})) {
      burst[actor] = burst[actor] || [];
      burst[actor].push([he, n]);
    }
  }
  const maxN = Math.max(1, ...Object.values(burst).flat().map(([, n]) => n));
  lanes.innerHTML = ALL_ACTORS.filter((a) => burst[a]).map((actor) => {
    const segs = burst[actor].map(([he, n]) => {
      const x0 = ((he - t0b) / Math.max(t1b - t0b, 1)) * 100;
      const w = Math.max((3600 / Math.max(t1b - t0b, 1)) * 100, 0.4);
      return `<div class="lane-burst" style="left:${x0.toFixed(2)}%;width:${w.toFixed(2)}%;opacity:${(0.2 + 0.8 * n / maxN).toFixed(2)}" title="${esc(new Date(he * 1000).toISOString())} — ${n} by ${esc(actor)}"></div>`;
    }).join("");
    return `<div class="lane-row"><div class="lane-name">${esc(actor.split("@")[0])}</div><div class="lane-track">${segs}</div></div>`;
  }).join("");

  // one click, both readings: the point becomes the rewind point, and the
  // nearest mark (within 8 viewBox units) is read. With 400+ marks in a
  // 25-hour window, "empty space" is too rare to gate the main action on.
  svg.onclick = (ev) => {
    const rect = svg.getBoundingClientRect();
    const frac = (ev.clientX - rect.left) / rect.width;
    const epoch = ov.since_epoch + frac * (t1 - ov.since_epoch);
    setRewindPoint(epoch);
    const cx = frac * W;
    let best = null, bestD = 9;
    for (const m of ov.marks) {
      if (!MARK_STYLE[m.kind]) continue;
      const d = Math.abs(timeX(ov, m.at_epoch, W) - cx);
      if (d < bestD) { bestD = d; best = m; }
    }
    if (best) showMarkDetail(best);
  };
}

function showMarkDetail(m) {
  if (!m) return;
  const el = $("mark-detail");
  el.classList.remove("hidden");
  const st = MARK_STYLE[m.kind] || { label: m.kind };
  el.innerHTML = `<b>${esc(st.label)}</b> · ${esc(fmtD(m.at))}${m.seq ? ` · seq ${m.seq}` : ""}` +
    (m.reason ? `<div>${esc(m.reason)}</div>` : "") +
    (m.family ? `<div>family: ${esc(m.family)}${m.title ? ` — “${esc(m.title)}”` : ""}</div>` : "");
}

function setRewindPoint(epoch) {
  if (!isFinite(epoch)) return;
  REWIND_POINT = { at_epoch: epoch };
  $("rewind-point-line").textContent =
    `rewind point: ${fmtD(new Date(epoch * 1000).toISOString().replace(".000Z", "Z"))} (set on the timeline)`;
  $("rewind-preview-btn").disabled = false;
  renderScrubber(OVERVIEW);
}

/* ----------------------------------------------------------------- lanes */

function renderLanes(lanes) {
  const rows = lanes.map((l) => {
    if (l.role === "character") {
      return `<tr class="character"><td>${esc(l.actor)}</td><td>${l.plays}</td>` +
        `<td>${l.win_rate ?? "—"} (${l.win ?? 0}/${l.plays})</td>` +
        `<td>${l.plays_per_hour ?? "—"}</td><td>${fmtT(l.last_at)}</td></tr>`;
    }
    if (l.role === "judge") {
      return `<tr><td>judge</td><td>${l.verdicts} verdicts</td>` +
        `<td>${l.refusal_rate ?? "—"} refused</td>` +
        `<td>${(l.tokens / 1e6).toFixed(2)}M tok · ${l.gpu_minutes.toFixed(1)} gpu-min</td>` +
        `<td>${fmtT(l.last_at)}</td></tr>`;
    }
    if (l.role === "engineer") {
      return `<tr><td>seed</td><td>${l.authored} authored</td><td>—</td><td>—</td><td>${fmtT(l.last_at)}</td></tr>`;
    }
    return `<tr><td>mediator</td><td>${l.retired} retired</td><td>—</td><td>—</td><td>${fmtT(l.last_at)}</td></tr>`;
  }).join("");
  $("lanes").innerHTML = `<table><thead><tr><th>actor</th><th>work in the window</th>` +
    `<th>outcome</th><th>rate / spend</th><th>last</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* ---------------------------------------------------------------- thread */

function renderThread(ov) {
  const judge = ov.lanes.find((l) => l.role === "judge") || {};
  const levels = ov.drift.levels || {};
  const rows = [
    { k: "the judge's verdicts in the window",
      v: judge.verdicts != null
        ? `${judge.verdicts}, of which ${judge.refused} refused (${judge.refusal_rate ?? "—"})`
        : "none in the window",
      bad: (judge.refusal_rate ?? 0) >= 0.5 },
    { k: "drift alarms in the window",
      v: ov.drift.available
        ? `hard ${levels.hard || 0} · tier ${levels.tier || 0} · soft ${levels.soft || 0}`
        : `unavailable (${ov.drift.error})`,
      bad: (levels.hard || 0) > 0 },
    { k: "auto-pause", v: ov.pause ? ov.pause.note : "no pause file is live", bad: false },
    { k: "precedent questions", v: "listed above — answer inline", bad: false },
  ];
  $("thread").innerHTML = rows.map((r) =>
    `<div class="row${r.bad ? " bad" : ""}"><span>${esc(r.k)}</span><span>${esc(r.v)}</span></div>`).join("");
}

/* ---------------------------------------------------------------- undone */

function renderUndone(ov) {
  const retired = ov.retired_recent || [];
  const table = retired.length
    ? `<table><thead><tr><th>when</th><th>family</th><th>why</th><th>plays</th></tr></thead><tbody>` +
      retired.map((r) => `<tr><td>${fmtD(r.at)}</td><td>${esc(r.family)}</td>` +
        `<td>${esc(r.reason)}</td><td>${r.plays ?? "—"}</td></tr>`).join("") + `</tbody></table>`
    : "<p>No skill was retired in the window.</p>";
  $("undone").innerHTML =
    `<p class="hint">This world's ledger carries no rewind events and no explicit reject events —
     what it undoes, it undoes by retiring (superseding) skills.</p>` + table;
  buildRewindControls();
}

function buildRewindControls() {
  const mk = (box, items, checked) => {
    box.innerHTML = "";
    for (const it of items) {
      const id = `keep-${it.replace(/[^a-z]/gi, "")}`;
      const label = document.createElement("label");
      label.innerHTML = `<input type="checkbox" value="${esc(it)}"${checked ? " checked" : ""}> ${esc(it)}`;
      box.appendChild(label);
    }
  };
  mk($("keep-actors"), ALL_ACTORS, false);
  mk($("keep-kinds"), ALL_KINDS, true);
  $("rewind-preview-btn").onclick = previewRewind;
}

async function previewRewind() {
  if (!REWIND_POINT) return;
  const actors = [...$("keep-actors").querySelectorAll("input:checked")].map((i) => i.value);
  const kinds = [...$("keep-kinds").querySelectorAll("input:checked")].map((i) => i.value);
  const btn = $("rewind-preview-btn");
  btn.disabled = true; btn.textContent = "previewing…";
  try {
    const res = await api("/api/rewind/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ at_epoch: REWIND_POINT.at_epoch, actors, kinds }),
    });
    const el = $("rewind-result");
    el.classList.remove("hidden");
    if (res.error) { el.innerHTML = `<div class="dropped">${esc(res.error)}</div>`; return; }
    const kindRows = Object.entries(res.kept_by_kind).map(([k, n]) => `<tr><td>${esc(k)}</td><td>${n}</td></tr>`).join("");
    const reasons = Object.entries(res.drop_reasons).map(([r, n]) => `<tr><td>${esc(r)}</td><td>${n}</td></tr>`).join("");
    el.innerHTML =
      `<div>the fork it would make:</div><div class="fork">${esc(res.fork)}</div>` +
      `<div>branching at <b>${esc(res.point.at)}</b> (seq ${res.point.seq}, a ${esc(res.point.kind)} by ${esc(res.point.actor)}) — ` +
      `<span class="kept">${res.kept} events kept</span>, <span class="dropped">${res.dropped} left behind</span> of ${res.rows_after_point} after the point.</div>` +
      (kindRows ? `<table><tr><th>kept by kind</th><th></th></tr>${kindRows}</table>` : "") +
      (reasons ? `<table><tr><th>left behind, why</th><th>rows</th></tr>${reasons}</table>` : "") +
      `<div class="expr">selection: ${esc(res.expression)}</div>` +
      `<div class="guarantee">${esc(res.guarantee)}. ${esc(res.canon)}.</div>`;
  } catch (e) {
    console.error(e);
  } finally {
    btn.disabled = false; btn.textContent = "preview the fork";
  }
}

/* ------------------------------------------------------------ precedents */

async function loadPrecedents() {
  const data = await api("/api/precedent?human=" + encodeURIComponent(OVERVIEW.human));
  const box = $("precedents");
  const pending = data.pending || [];
  PENDING_COUNT = pending.length;
  if (!pending.length) {
    box.innerHTML = `<p class="hint">No pending questions. ${data.source === "stub (core.precedent not landed on main)"
      ? "The stub asks only what the ledger justifies; nothing in the window needs a ruling."
      : ""}</p>`;
  } else {
    box.innerHTML = pending.map((p) => questionHTML(p)).join("");
    box.querySelectorAll("button[data-id]").forEach((b) => (b.onclick = () => answerPrecedent(b.dataset.id, b.dataset.ruling, b.dataset.human)));
  }
  const recent = (data.recent || []).filter((p) => p.status === "adjudicated").slice(-4);
  const note = recent.length
    ? `<p class="hint">recent rulings: ` + recent.map((p) =>
        `${esc(p.metadata && p.metadata.ruling)} by ${esc((p.metadata && p.metadata.ruled_by) || "?")} (${fmtD(p.created_at)})`).join(" · ") + `</p>`
    : "";
  box.insertAdjacentHTML("beforeend", note + `<p class="hint">source: ${esc(data.source)}</p>`);
}

function questionHTML(p) {
  const options = (p.metadata && p.metadata.options) || [];
  return `<div class="question" id="q-${esc(p.id)}">
    <div class="decision">${esc(p.decision)}</div>
    <div class="meta">asked ${fmtD(p.created_at)} · ${esc(p.author)} · keys: ${(p.keys || []).map(esc).join(", ")}</div>
    <div class="choices">${options.map((o) =>
      `<button data-id="${esc(p.id)}" data-ruling="${esc(o.ruling)}" data-human="${esc(OVERVIEW.human)}">${esc(o.label)}</button>`).join("")}
      <input class="note" id="note-${esc(p.id)}" placeholder="a line of why (kept with the ruling)">
    </div>
  </div>`;
}

async function answerPrecedent(id, ruling, human) {
  const note = ($("note-" + id) || {}).value || "";
  try {
    await api("/api/precedent", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ruling, note, human }),
    });
    await loadPrecedents();
    await load(OVERVIEW.human); // the thread and the letter both change
  } catch (e) {
    console.error(e);
  }
}

/* ------------------------------------------------------------------ next */

function renderNext(ov) {
  const levels = ov.drift.levels || {};
  const quiet = PENDING_COUNT === 0 && !(levels.hard || 0) &&
    !(((ov.lanes.find((l) => l.role === "judge") || {}).refusal_rate ?? 0) >= 0.5);
  $("next").innerHTML =
    `<div class="quiet">${quiet
      ? "Nothing needs you. The world kept its own counsel while you were away, and that was fine."
      : "One thing is waiting above — answer it, and the quiet moment is next."}</div>` +
    `<p>While you are gone the world keeps playing; the ledger keeps every row; the next letter
       is written when you come back. The rewind panel above is ready if any of this went wrong.</p>`;
}

/* ------------------------------------------------------------------ boot */

$("ask-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const q = $("ask-input").value.trim();
  if (!q) return;
  const box = $("ask-answer");
  box.classList.remove("hidden");
  box.innerHTML = "<p class='hint'>pulling the slice that answers it…</p>";
  try {
    const a = await api("/api/ask?q=" + encodeURIComponent(q) + "&human=" + encodeURIComponent(OVERVIEW.human));
    const sample = (a.sample || []).slice(-10).map((r) =>
      `<tr><td>${fmtT(r.at)}</td><td>${esc(r.kind)}</td><td>${esc(r.actor)}</td>` +
      `<td>${esc(r.verdict || r.title || r.family || (r.refused ? "refused" : ""))}</td>` +
      `<td>${esc(r.detail || r.reason || r.skill || "")}</td></tr>`).join("");
    box.innerHTML =
      `<p>${esc(a.summary)}</p>` +
      `<p class="pulled">pulled ${a.matched} of ${a.of_total_rows} rows (${(a.fraction_of_ledger * 100).toFixed(2)}% of the ledger)
        ${a.window ? `between ${fmtD(a.window[0])} and ${fmtD(a.window[1])}` : ""}</p>` +
      `<p class="expr">the selection it ran: ${esc(a.expression)}</p>` +
      (sample ? `<table><tr><th>at</th><th>kind</th><th>actor</th><th>what</th><th>detail</th></tr>${sample}</table>` : "");
  } catch (e) {
    box.innerHTML = `<p class="dropped">${esc(String(e))}</p>`;
    console.error(e);
  }
};

$("human-select").onchange = (ev) => load(ev.target.value);
$("mark-seen").onclick = async () => {
  try {
    await api("/api/visit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ human: OVERVIEW.human }),
    });
    await load(OVERVIEW.human);
  } catch (e) { console.error(e); }
};

load().catch((e) => {
  document.body.insertAdjacentHTML("afterbegin",
    `<div style="background:#a02c2c;color:#fff;padding:8px 14px">could not read the world: ${esc(String(e))}</div>`);
  console.error(e);
});
