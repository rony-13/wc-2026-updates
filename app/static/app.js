"use strict";

const CFG = window.WC_CONFIG || { todayInterval: 30, groupsInterval: 60 };
const $ = (sel) => document.querySelector(sel);

// user preferences (favorite + following), loaded from the backend
let prefs = { favorite: null, following: [] };
let teams = [];
let lastGroups = null;   // cache last payloads so we can re-render on pref change
let lastToday = null;
let lastBracket = null;
let activeTab = "group_stage";
let defaultTabSet = false;  // only auto-pick the current-stage tab once, on first load
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

function scorersLine(scorers) {
  if (!scorers || !scorers.length) return "";
  const text = scorers.map(escapeHtml).join(", ");
  return `<div style="font-size:12px;color:var(--muted);margin:2px 0 6px;line-height:1.45;">${text}</div>`;
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
      ${scorersLine(m.home_scorers)}
      <div class="sc-row"><span class="sc-team">${teamLabel(m.away)}</span><span class="sc-score">${as}</span></div>
      ${scorersLine(m.away_scorers)}
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

/* ---- merged knockout bracket (Round of 32 -> Final, one connected chart) */

// Flag emoji lookup. Plain ISO 3166-1 alpha-2 codes render as regional
// indicator pairs; England and Scotland aren't sovereign countries and use
// the special Unicode "tag sequence" flag form instead (built from
// codepoints, not literal characters, to avoid any encoding mishaps).
function regionalFlag(code) {
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 127397 + c.charCodeAt(0)));
}
function tagFlag(tag) {
  const codes = [0x1f3f4];
  for (const ch of tag) codes.push(0xe0000 + ch.charCodeAt(0));
  codes.push(0xe007f);
  return String.fromCodePoint(...codes);
}
const FLAG_SPECIAL = { ENG: tagFlag("gbeng"), SCT: tagFlag("gbsct") };
const TEAM_FLAGS = {
  "mexico": "MX", "south africa": "ZA", "south korea": "KR", "korea republic": "KR",
  "czechia": "CZ", "czech republic": "CZ",
  "canada": "CA", "switzerland": "CH",
  "bosnia and herzegovina": "BA", "bosnia & herzegovina": "BA", "bosnia-herzegovina": "BA",
  "qatar": "QA",
  "brazil": "BR", "morocco": "MA", "haiti": "HT", "scotland": "SCT",
  "united states": "US", "usa": "US", "united states of america": "US",
  "paraguay": "PY", "australia": "AU",
  "türkiye": "TR", "turkiye": "TR", "turkey": "TR",
  "germany": "DE", "curaçao": "CW", "curacao": "CW",
  "ivory coast": "CI", "côte d'ivoire": "CI", "cote d'ivoire": "CI",
  "ecuador": "EC",
  "netherlands": "NL", "japan": "JP", "sweden": "SE", "tunisia": "TN",
  "belgium": "BE", "egypt": "EG", "iran": "IR", "new zealand": "NZ",
  "spain": "ES", "cape verde": "CV", "cabo verde": "CV",
  "saudi arabia": "SA", "uruguay": "UY",
  "france": "FR", "senegal": "SN", "iraq": "IQ", "norway": "NO",
  "argentina": "AR", "algeria": "DZ", "austria": "AT", "jordan": "JO",
  "portugal": "PT",
  "dr congo": "CD", "congo dr": "CD", "democratic republic of the congo": "CD",
  "uzbekistan": "UZ", "colombia": "CO",
  "england": "ENG",
  "croatia": "HR", "ghana": "GH", "panama": "PA",
};
function flagFor(team) {
  if (!team) return "";
  const code = TEAM_FLAGS[team.toLowerCase().trim()];
  if (!code) return "";
  return FLAG_SPECIAL[code] || regionalFlag(code);
}

// Bracket topology -- which match ids sit in which column, top-to-bottom,
// derived directly from (and verified against) the real R32/R16/QF/SF/Final
// templates in app/knockout.py: each side's columns are nested in nasting
// order so connector lines never cross.
const BRACKET_LAYOUT = {
  r32_left: [74, 77, 73, 75, 83, 84, 81, 82],
  r16_left: [89, 90, 93, 94],
  qf_left: [97, 98],
  sf_left: [101],
  r32_right: [76, 78, 79, 80, 86, 88, 85, 87],
  r16_right: [91, 92, 95, 96],
  qf_right: [99, 100],
  sf_right: [102],
  final: 104,
  third: 103,
};
const PARENT_OF = {
  74: 89, 77: 89, 73: 90, 75: 90, 76: 91, 78: 91, 79: 92, 80: 92,
  83: 93, 84: 93, 81: 94, 82: 94, 86: 95, 88: 95, 85: 96, 87: 96,
  89: 97, 90: 97, 93: 98, 94: 98, 91: 99, 92: 99, 95: 100, 96: 100,
  97: 101, 98: 101, 99: 102, 100: 102, 101: 104, 102: 104,
};
const SIDE_OF = {};
for (const mid of [...BRACKET_LAYOUT.r32_left, ...BRACKET_LAYOUT.r16_left, ...BRACKET_LAYOUT.qf_left, ...BRACKET_LAYOUT.sf_left]) {
  SIDE_OF[mid] = "left";
}
for (const mid of [...BRACKET_LAYOUT.r32_right, ...BRACKET_LAYOUT.r16_right, ...BRACKET_LAYOUT.qf_right, ...BRACKET_LAYOUT.sf_right]) {
  SIDE_OF[mid] = "right";
}

function fixtureById(matchId) {
  if (!lastBracket) return null;
  const r = lastBracket.rounds;
  const all = [].concat(r.round_of_32, r.round_of_16, r.quarter_finals, r.semi_finals, r.final, r.third_place);
  return all.find((fx) => fx.match_id === matchId) || null;
}

function kickoffShort(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    return `${dd}/${mm}`;
  } catch (e) {
    return "";
  }
}

function bracketSideV2(side) {
  if (side.team) {
    const tier = classify(side.team);
    const cls = tier === "fav" ? "is-fav" : tier === "follow" ? "is-follow" : "";
    return { flag: flagFor(side.team), name: `<span class="bb-name ${cls}">${escapeHtml(side.team)}</span>` };
  }
  if (side.candidates && side.candidates.length) {
    return { flag: "", name: `<span class="bb-name bb-unknown">${side.candidates.map(escapeHtml).join(" / ")}</span>` };
  }
  return { flag: "", name: `<span class="bb-name bb-unknown">${escapeHtml(side.rule)}</span>` };
}

function bracketBoxV2(fx) {
  const decided = fx.score && fx.score.home !== fx.score.away;
  const homeWins = decided && fx.score.home > fx.score.away;
  const awayWins = decided && fx.score.away > fx.score.home;
  const h = bracketSideV2(fx.home);
  const a = bracketSideV2(fx.away);
  const dateLabel = kickoffShort(fx.kickoff);
  const hScore = fx.score ? `<span class="bb-score">${fx.score.home}</span>` : "";
  const aScore = fx.score ? `<span class="bb-score">${fx.score.away}</span>` : "";
  const pso = fx.decided_by_penalties ? `<div class="bb-pso">Decided on penalties</div>` : "";
  return `
    <div class="bb" data-match-id="${fx.match_id}">
      <div class="bb-meta"><span>[${fx.match_id}]</span><span>${dateLabel}</span></div>
      <div class="bb-row ${homeWins ? "bb-winner" : ""}">
        <span class="bb-flag">${h.flag}</span>${h.name}${hScore}
      </div>
      <div class="bb-row ${awayWins ? "bb-winner" : ""}">
        <span class="bb-flag">${a.flag}</span>${a.name}${aScore}
      </div>
      ${pso}
    </div>`;
}

function renderBracketColumn(hostId, matchIds) {
  const host = $(`#${hostId}`);
  if (!host) return;
  host.innerHTML = matchIds.map((mid) => {
    const fx = fixtureById(mid);
    return fx ? bracketBoxV2(fx) : "";
  }).join("");
}

function renderKnockoutBracket() {
  if (!lastBracket) return;
  renderBracketColumn("col-r32-left", BRACKET_LAYOUT.r32_left);
  renderBracketColumn("col-r16-left", BRACKET_LAYOUT.r16_left);
  renderBracketColumn("col-qf-left", BRACKET_LAYOUT.qf_left);
  renderBracketColumn("col-sf-left", BRACKET_LAYOUT.sf_left);
  renderBracketColumn("col-sf-right", BRACKET_LAYOUT.sf_right);
  renderBracketColumn("col-qf-right", BRACKET_LAYOUT.qf_right);
  renderBracketColumn("col-r16-right", BRACKET_LAYOUT.r16_right);
  renderBracketColumn("col-r32-right", BRACKET_LAYOUT.r32_right);

  const finalFx = fixtureById(BRACKET_LAYOUT.final);
  const thirdFx = fixtureById(BRACKET_LAYOUT.third);
  $("#col-final-match").innerHTML = finalFx ? bracketBoxV2(finalFx) : "";
  $("#col-third-match").innerHTML = thirdFx ? bracketBoxV2(thirdFx) : "";

  drawBracketLines();
}

function drawBracketLines() {
  const wrap = $("#bracket-wrap");
  const svg = $("#bracket-lines");
  if (!wrap || !svg || wrap.offsetParent === null) return;  // hidden tab right now
  const wrapRect = wrap.getBoundingClientRect();
  svg.setAttribute("width", wrap.scrollWidth);
  svg.setAttribute("height", wrap.scrollHeight);
  svg.innerHTML = "";

  const ns = "http://www.w3.org/2000/svg";
  function pointFor(matchId, edge) {
    const el = wrap.querySelector(`[data-match-id="${matchId}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      x: (edge === "right" ? r.right : r.left) - wrapRect.left + wrap.scrollLeft,
      y: r.top + r.height / 2 - wrapRect.top + wrap.scrollTop,
    };
  }

  Object.keys(PARENT_OF).forEach((key) => {
    const childId = Number(key);
    const parentId = PARENT_OF[childId];
    const side = SIDE_OF[childId];
    const p1 = pointFor(childId, side === "left" ? "right" : "left");
    const p2 = pointFor(parentId, side === "left" ? "left" : "right");
    if (!p1 || !p2) return;

    const fx = fixtureById(childId);
    const decided = fx && fx.score && fx.score.home !== fx.score.away;
    const midX = (p1.x + p2.x) / 2;
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", `M ${p1.x},${p1.y} H ${midX} V ${p2.y} H ${p2.x}`);
    path.setAttribute("stroke", decided ? "var(--qualify)" : "var(--muted)");
    path.setAttribute("stroke-width", decided ? 2 : 1.4);
    path.setAttribute("fill", "none");
    svg.appendChild(path);
  });
}

async function loadBracket() {
  try {
    const res = await fetch("/api/knockout/bracket", { cache: "no-store" });
    const data = await res.json();
    lastBracket = data;
    renderKnockoutBracket();
    if (!defaultTabSet) {
      defaultTabSet = true;
      const tab = (data.current_stage && data.current_stage !== "group_stage") ? "knockout_stage" : "group_stage";
      setActiveTab(tab);
    }
  } catch (e) {
    // bracket data is supplementary -- a failed fetch here shouldn't disturb
    // the rest of the page or its connection-status indicator
  }
}

function setActiveTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".stage-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== tab;
  });
  if (tab === "knockout_stage") {
    // boxes were just unhidden, so their layout didn't exist a moment ago
    requestAnimationFrame(() => drawBracketLines());
  }
}

function wireTabs() {
  document.querySelectorAll(".stage-tab").forEach((btn) => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  });
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (activeTab === "knockout_stage") drawBracketLines(); }, 150);
  });
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
  renderKnockoutBracket();
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
  const myTeamsBtn = $("#myteams-btn");
  if (!myTeamsBtn) return;  // hidden server-side in read-only (public) mode
  myTeamsBtn.addEventListener("click", () =>
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

/* ---- theme (dark / light / system) ------------------------------------- */
const THEME_KEY = "wc2026-theme";

function systemPrefersDark() {
  return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
}

function resolveTheme(choice) {
  return choice === "system" ? (systemPrefersDark() ? "dark" : "light") : choice;
}

function applyTheme(choice) {
  document.documentElement.dataset.theme = resolveTheme(choice);
  document.querySelectorAll(".theme-opt").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.themeChoice === choice);
  });
}

function initTheme() {
  let saved = "system";
  try { saved = localStorage.getItem(THEME_KEY) || "system"; } catch (e) {}
  applyTheme(saved);

  document.querySelectorAll(".theme-opt").forEach((btn) => {
    btn.addEventListener("click", () => {
      const choice = btn.dataset.themeChoice;
      try { localStorage.setItem(THEME_KEY, choice); } catch (e) {}
      applyTheme(choice);
    });
  });

  // if the user is following "system" and the OS theme changes while the
  // app is open, update live rather than waiting for a reload
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      let current = "system";
      try { current = localStorage.getItem(THEME_KEY) || "system"; } catch (e) {}
      if (current === "system") applyTheme("system");
    });
  }
}

/* ---- startup ---------------------------------------------------------- */
function start(fn, seconds) {
  fn();
  setInterval(fn, seconds * 1000);
}

// Live local clock in the topbar -- the viewer's own device time/timezone
// (same standard used for kickoff times elsewhere), not a fixed host zone.
function tickClock() {
  const el = $("#topbar-clock");
  if (!el) return;
  el.textContent = new Date().toLocaleString(undefined, {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

(async function init() {
  initTheme();
  await Promise.all([loadPreferences(), loadTeams()]);
  wirePicker();
  wireTabs();
  setActiveTab("group_stage");  // sensible default while the real current stage loads
  start(loadToday, CFG.todayInterval);
  start(loadGroups, CFG.groupsInterval);
  start(loadBracket, CFG.bracketInterval);
  start(tickClock, 1);
  // refresh the team list periodically so it fills in once live data arrives
  setInterval(loadTeams, 5 * 60 * 1000);
})();
