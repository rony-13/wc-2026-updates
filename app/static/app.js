"use strict";

const CFG = window.WC_CONFIG || { todayInterval: 30, groupsInterval: 60 };
const $ = (sel) => document.querySelector(sel);

// user preferences (favorite + following), loaded from the backend
let prefs = { favorite: null, following: [] };
let teams = [];
let lastGroups = null;   // cache last payloads so we can re-render on pref change
let lastToday = null;
let followSet = new Set();

function rebuildFollowSet() {
  followSet = new Set((prefs.following || []).map((t) => t.casefold ? t.casefold() : t.toLowerCase()));
}

// returns 'fav' | 'follow' | null for a team name (case-insensitive)
function classify(team) {
  if (!team) return null;
  const key = team.toLowerCase();
  if (prefs.favorite && prefs.favorite.toLowerCase() === key) return "fav";
  if (followSet.has(key)) return "follow";
  return null;
}

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

// Kickoff times render in the VIEWER'S OWN device timezone (standard practice
// for live-score apps — ESPN, FlashScore, BBC Sport all do this), not a fixed
// tournament-host timezone. utc_date is an absolute instant, so this is always
// correct regardless of where the backend server happens to run.
function kickoffLocal(utcIso) {
  if (!utcIso) return "—";
  return new Date(utcIso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// football-data.org is live; openfootball / seed are slower or offline.
function liveBadge(word, color) {
  return `<strong style="color:${color};font-weight:700;letter-spacing:.05em;">${word}</strong>`;
}

// worldcup26.ir / football-data.org = live; openfootball = not live; seed = offline cache.
function setStatus(meta, ok) {
  const el = $("#status");
  const dot = $("#status-dot");
  const text = $("#status-text");
  el.classList.remove("live");  // .live drives the green pulsing dot in style.css

  // Our own backend was unreachable (server not running / network blip).
  if (!ok || !meta) {
    dot.style.background = "var(--live)";          // red
    text.innerHTML = `${liveBadge("OFFLINE", "var(--live)")} · reconnecting…`;
    return;
  }

  const src = meta.source;
  const isLive = src === "worldcup26.ir" || src === "football-data.org";
  const when = `updated ${fmtUpdated(meta.updated_at)}`;

  if (isLive) {
    el.classList.add("live");                      // green + pulse (from style.css)
    dot.style.background = "";                      // let the .live class color the dot
    text.innerHTML = `${liveBadge("LIVE", "var(--qualify)")} · ${escapeHtml(src)} · ${when}`;
  } else if (src === "seed") {
    dot.style.background = "var(--muted)";          // grey
    text.innerHTML = `${liveBadge("OFFLINE", "var(--muted)")} · cached snapshot · ${when}`;
  } else {
    // openfootball (or any other non-live source): valid data, just not live.
    dot.style.background = "var(--accent)";         // amber
    const name = src === "openfootball" ? "openfootball (~daily)" : escapeHtml(src);
    text.innerHTML = `${liveBadge("NOT LIVE", "var(--accent)")} · ${name} · ${when}`;
  }
  $("#foot-source").textContent = `Source: ${escapeHtml(src)}`;
}

/* ---- today scorecards ------------------------------------------------- */
function teamLabel(name) {
  const cls = classify(name);
  const star = cls === "fav" ? '<span class="team-star">★</span>' : "";
  return `${star}${escapeHtml(name)}`;
}

function scorecard(m) {
  const live = m.is_live;
  const finished = m.status === "FINISHED";
  let cls = live ? "is-live" : finished ? "ft" : "sched";
  // a favorite/followed team playing today tints the whole card (favorite wins)
  const tier = classify(m.home) === "fav" || classify(m.away) === "fav" ? "fav-card"
    : classify(m.home) === "follow" || classify(m.away) === "follow" ? "follow-card"
    : "";
  if (tier) cls += " " + tier;
  let state;
  if (live) state = `<span class="sc-state live">${m.minute ? m.minute + "'" : "LIVE"}</span>`;
  else if (finished) state = `<span class="sc-state ft">Full time</span>`;
  else state = `<span class="sc-state">${escapeHtml(kickoffLocal(m.utc_date))}</span>`;

  const hs = m.home_score == null ? "–" : m.home_score;
  const as = m.away_score == null ? "–" : m.away_score;
  const group = m.group ? escapeHtml(m.group) : escapeHtml((m.stage || "").replace(/_/g, " "));

  return `
    <div class="scorecard ${cls}" role="listitem">
      <div class="sc-top"><span class="sc-group">${group}</span>${state}</div>
      <div class="sc-row"><span class="sc-team">${teamLabel(m.home)}</span><span class="sc-score">${hs}</span></div>
      <div class="sc-row"><span class="sc-team">${teamLabel(m.away)}</span><span class="sc-score">${as}</span></div>
      ${m.venue ? `<div class="sc-venue">${escapeHtml(m.venue)}</div>` : ""}
    </div>`;
}

async function loadToday() {
  try {
    const res = await fetch("/api/today", { cache: "no-store" });
    const data = await res.json();
    setStatus(data, true);
    lastToday = data;
    $("#today-date").textContent = new Date(data.date + "T00:00:00")
      .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    renderToday();
  } catch (e) {
    setStatus(null, false);
  }
}

/* ---- group tables ----------------------------------------------------- */
function groupCard(g) {
  const rows = g.rows.map((r) => {
    const tier = classify(r.team);          // 'fav' | 'follow' | null
    const cls = [r.qualifies ? "qualify" : "", tier === "fav" ? "is-fav" : tier === "follow" ? "is-follow" : ""]
      .filter(Boolean).join(" ");
    const star = tier === "fav" ? "★" : "";
    return `
    <tr class="${cls}">
      <td class="team-col"><span class="team-wrap"><span class="star-slot">${star}</span><span class="pos">${r.rank}</span>${escapeHtml(r.team)}</span></td>
      <td>${r.played}</td>
      <td>${r.won}-${r.draw}-${r.lost}</td>
      <td>${r.goal_difference > 0 ? "+" : ""}${r.goal_difference}</td>
      <td class="pts">${r.points}</td>
    </tr>`;
  }).join("");
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

function renderToday() {
  if (!lastToday) return;
  const host = $("#today");
  if (!lastToday.matches.length) {
    host.innerHTML = `<p class="empty">No matches scheduled for today.</p>`;
  } else {
    host.innerHTML = lastToday.matches.map(scorecard).join("");
  }
}

function renderGroups() {
  if (!lastGroups) return;
  $("#groups").innerHTML = lastGroups.groups.map(groupCard).join("");
}

async function loadGroups() {
  try {
    const res = await fetch("/api/groups", { cache: "no-store" });
    const data = await res.json();
    setStatus(data, true);
    lastGroups = data;
    renderGroups();
  } catch (e) {
    setStatus(null, false);
  }
}

/* ---- preferences + team picker ---------------------------------------- */
async function loadPreferences() {
  try {
    const res = await fetch("/api/preferences", { cache: "no-store" });
    prefs = await res.json();
  } catch (e) {
    prefs = { favorite: null, following: [] };
  }
  rebuildFollowSet();
}

async function loadTeams() {
  try {
    const res = await fetch("/api/teams", { cache: "no-store" });
    teams = (await res.json()).teams || [];
  } catch (e) {
    teams = [];
  }
}

async function savePreferences() {
  rebuildFollowSet();
  // re-render immediately for a snappy feel; the PUT persists in the background
  renderToday();
  renderGroups();
  renderPicker();
  try {
    const res = await fetch("/api/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    });
    prefs = await res.json();   // adopt the server-normalized version
    rebuildFollowSet();
  } catch (e) { /* keep optimistic local state */ }
}

function setFavorite(team) {
  prefs.favorite = (prefs.favorite === team) ? null : team;
  if (prefs.favorite) {
    // a team can't be both favorite and followed
    prefs.following = (prefs.following || []).filter(
      (t) => t.toLowerCase() !== team.toLowerCase()
    );
  }
  savePreferences();
}

function toggleFollow(team) {
  const key = team.toLowerCase();
  if (prefs.favorite && prefs.favorite.toLowerCase() === key) {
    prefs.favorite = null;   // move favorite -> following
  }
  const exists = (prefs.following || []).some((t) => t.toLowerCase() === key);
  prefs.following = exists
    ? prefs.following.filter((t) => t.toLowerCase() !== key)
    : [...(prefs.following || []), team];
  savePreferences();
}

function renderPicker() {
  const list = $("#picker-list");
  if (!list) return;
  const q = ($("#picker-search").value || "").toLowerCase().trim();
  const shown = teams.filter((t) => t.toLowerCase().includes(q));
  if (!shown.length) {
    list.innerHTML = `<p class="picker-empty">No teams match “${escapeHtml(q)}”.</p>`;
    return;
  }
  list.innerHTML = shown.map((t) => {
    const tier = classify(t);
    const rowCls = tier === "fav" ? "fav" : tier === "follow" ? "follow" : "";
    const starTitle = tier === "fav" ? "Remove favorite" : "Set as favorite";
    const followLabel = tier === "follow" ? "Following" : "Follow";
    return `
      <div class="pick-row ${rowCls}" data-team="${escapeHtml(t)}">
        <button type="button" class="pick-btn pick-star" data-act="fav" title="${starTitle}" aria-label="${starTitle}">★</button>
        <span class="pick-name">${escapeHtml(t)}</span>
        <button type="button" class="pick-btn pick-follow" data-act="follow">${followLabel}</button>
      </div>`;
  }).join("");
}

function openPicker() {
  $("#picker").hidden = false;
  $("#picker-backdrop").hidden = false;
  $("#myteams-btn").setAttribute("aria-expanded", "true");
  renderPicker();
  $("#picker-search").focus();
}

function closePicker() {
  $("#picker").hidden = true;
  $("#picker-backdrop").hidden = true;
  $("#myteams-btn").setAttribute("aria-expanded", "false");
}

function wirePicker() {
  $("#myteams-btn").addEventListener("click", () =>
    $("#picker").hidden ? openPicker() : closePicker()
  );
  $("#picker-close").addEventListener("click", closePicker);
  $("#picker-backdrop").addEventListener("click", closePicker);
  $("#picker-search").addEventListener("input", renderPicker);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#picker").hidden) closePicker();
  });
  // event delegation for the per-team buttons
  $("#picker-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".pick-btn");
    if (!btn) return;
    const team = btn.closest(".pick-row").dataset.team;
    if (btn.dataset.act === "fav") setFavorite(team);
    else toggleFollow(team);
  });
}

/* ---- startup ---------------------------------------------------------- */
function start(fn, seconds) {
  fn();
  setInterval(fn, seconds * 1000);
}

(async function init() {
  await Promise.all([loadPreferences(), loadTeams()]);
  wirePicker();
  start(loadToday, CFG.todayInterval);
  start(loadGroups, CFG.groupsInterval);
  // refresh the team list periodically so it fills in once live data arrives
  setInterval(loadTeams, 5 * 60 * 1000);
})();
