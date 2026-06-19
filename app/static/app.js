"use strict";

const CFG = window.WC_CONFIG || { todayInterval: 30, groupsInterval: 60 };
const $ = (sel) => document.querySelector(sel);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmtUpdated(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const secs = Math.round((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return secs <= 5 ? "just now" : `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  return d.toLocaleString();
}

// football-data.org is live; openfootball / seed are slower or offline.
function setStatus(meta, ok) {
  const el = $("#status");
  const text = $("#status-text");
  const live = meta && meta.source === "football-data.org";
  el.classList.remove("live", "offline", "error");
  if (!ok) {
    el.classList.add("error");
    text.textContent = "Reconnecting…";
    return;
  }
  if (live) el.classList.add("live");
  else if (meta.source === "seed") el.classList.add("offline");
  const label = meta.source === "seed" ? "Offline snapshot"
    : meta.source === "openfootball" ? "openfootball (~daily)"
    : "Live · football-data.org";
  text.textContent = `${label} · updated ${fmtUpdated(meta.updated_at)}`;
  $("#foot-source").textContent = `Source: ${meta.source}`;
}

/* ---- today scorecards ------------------------------------------------- */
function scorecard(m) {
  const live = m.is_live;
  const finished = m.status === "FINISHED";
  const cls = live ? "is-live" : finished ? "ft" : "sched";
  let state;
  if (live) state = `<span class="sc-state live">${m.minute ? m.minute + "'" : "LIVE"}</span>`;
  else if (finished) state = `<span class="sc-state ft">Full time</span>`;
  else state = `<span class="sc-state">${escapeHtml(m.kickoff_local)}</span>`;

  const hs = m.home_score == null ? "–" : m.home_score;
  const as = m.away_score == null ? "–" : m.away_score;
  const group = m.group ? escapeHtml(m.group) : escapeHtml((m.stage || "").replace(/_/g, " "));

  return `
    <div class="scorecard ${cls}" role="listitem">
      <div class="sc-top"><span class="sc-group">${group}</span>${state}</div>
      <div class="sc-row"><span class="sc-team">${escapeHtml(m.home)}</span><span class="sc-score">${hs}</span></div>
      <div class="sc-row"><span class="sc-team">${escapeHtml(m.away)}</span><span class="sc-score">${as}</span></div>
      ${m.venue ? `<div class="sc-venue">${escapeHtml(m.venue)}</div>` : ""}
    </div>`;
}

async function loadToday() {
  try {
    const res = await fetch("/api/today", { cache: "no-store" });
    const data = await res.json();
    setStatus(data, true);
    $("#today-date").textContent = new Date(data.date + "T00:00:00")
      .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    const host = $("#today");
    if (!data.matches.length) {
      host.innerHTML = `<p class="empty">No matches scheduled for today.</p>`;
    } else {
      host.innerHTML = data.matches.map(scorecard).join("");
    }
  } catch (e) {
    setStatus(null, false);
  }
}

/* ---- group tables ----------------------------------------------------- */
function groupCard(g) {
  const rows = g.rows.map((r) => `
    <tr class="${r.qualifies ? "qualify" : ""}">
      <td class="team-col"><span class="pos">${r.rank}</span>${escapeHtml(r.team)}</td>
      <td>${r.played}</td>
      <td>${r.won}-${r.draw}-${r.lost}</td>
      <td>${r.goal_difference > 0 ? "+" : ""}${r.goal_difference}</td>
      <td class="pts">${r.points}</td>
    </tr>`).join("");
  return `
    <div class="groupcard">
      <div class="gc-head">${escapeHtml(g.group)}</div>
      <table class="table">
        <thead><tr>
          <th class="team-col">Team</th><th>P</th><th>W-D-L</th><th>GD</th><th>Pts</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function loadGroups() {
  try {
    const res = await fetch("/api/groups", { cache: "no-store" });
    const data = await res.json();
    setStatus(data, true);
    $("#groups").innerHTML = data.groups.map(groupCard).join("");
  } catch (e) {
    setStatus(null, false);
  }
}

function start(fn, seconds) {
  fn();
  setInterval(fn, seconds * 1000);
}

start(loadToday, CFG.todayInterval);
start(loadGroups, CFG.groupsInterval);
// keep the "updated Ns ago" label honest between polls
setInterval(() => {
  const t = $("#status-text");
  if (t && t.dataset) { /* refreshed on next poll */ }
}, 1000);
