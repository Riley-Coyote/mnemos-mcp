/* The log. Reads ../data/life.json (small, every 20 seconds) and ../data/memories.json (when the memory changes), both
 * made read-only on request by `mnemos log` for whichever mind it was started with. Nothing here writes anywhere. */

import { Room, parseRoute, placeOf } from '../shared/room.js';
import { esc, at, ago, clock, dayName, plural, temperature, tempWord, KIND, sameModel, modelName } from '../shared/words.js';

const $ = (id) => document.getElementById(id);
const nav = document.querySelector('.nav');
const EVERY = 20_000;
const STALE_AFTER = 3 * 60_000;              // every read is fresh; three minutes without one means `mnemos log` stopped
const TABS = ['you', 'log', 'memories'];        // the three places: for you, its life, its memory
const ROUTES = ['you', 'notes', 'log', 'journal', 'hours', 'memories', 'beliefs', 'questions', 'desk'];   // every view, for links

let life = null, mems = [], byId = new Map(), version = null, room = null;

async function json(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

/* ---------- who, how warm, and what you can check ---------- */

function head() {
  const who = life.identity, h = life.hours[0] || null, k = temperature(h);
  document.title = `${who.name} · the log`;
  $('name').textContent = who.name;
  const dot = $('dot');
  dot.classList.toggle('cold', !h || k < 0.1);
  dot.style.setProperty('--k', String(h ? Math.max(0, Math.min(1, k)) : 0));
  if (!h) {
    $('state').innerHTML = `${plural(life.memory.count, 'memory', 'memories')} · no quiet hours yet`;
  } else {
    const end = at(h.end), stale = Date.now() - end.getTime() > 26 * 36e5;
    $('state').innerHTML = `<b>${tempWord(k, h)}</b> · ${(KIND[h.kind] || esc(h.kind)).toLowerCase()} ended ${ago(Date.now() - end.getTime())}${h.practice ? ' · practice' : ''}${stale ? ' · no hour since' : ''}`;
  }
  const v = [];
  if (h) {
    v.push(h.model && who.model && !sameModel(h.model, who.model)
      ? `<span class="flag">ran as ${esc(modelName(h.model))}; nothing it wrote was kept</span>` : `<span class="ok">ran as ${esc(h.modelName || who.name)}</span>`);
    if (h.practice) v.push(h.check === 'rows' ? (h.untouched === false ? '<span class="flag">left something in the real memory</span>' : '<span>real memory untouched</span>') : '<span>checked the older way</span>');
    const refused = [...new Set(h.refused || [])];
    v.push(refused.length ? `<span class="flag">${plural(refused.length, 'tool')} refused</span>` : '<span>nothing refused</span>');
    if (h.status !== 'done' || h.reason) v.push(`<span class="flag">${esc(h.reason || h.status)}</span>`);
  }
  const plan = life.schedule || [];
  v.push(plan.length ? `<span>next hour ${plan[0].when && !Array.isArray(plan[0].when) ? `at ${String(plan[0].when.Hour ?? 0).padStart(2, '0')}:${String(plan[0].when.Minute ?? 0).padStart(2, '0')}` : 'scheduled'}${plan[0].loaded ? '' : ', but not loaded'}</span>` : '<span>hours not scheduled</span>');
  const made = at(life.made), stale = Date.now() - made.getTime() > STALE_AFTER;
  v.push(`<span class="fresh">${stale ? `stopped updating ${ago(Date.now() - made.getTime())}` : `read ${ago(Date.now() - made.getTime())}`}</span>`);
  const el = $('verify'); el.innerHTML = v.join(''); el.classList.toggle('stale', stale);
}

/* ---------- the margin: its state beside its life ---------- */

const madeLately = () => life.studio.filter((f) => f.picture).slice(0, 3);
const when = (iso) => { const d = at(iso); return `${dayName(d)}, ${clock(d)}`; };

/* the margin, beside its life: what it believes, and what it made lately. What it says to you is For you; its
   memory's questions and its notes to itself are in its memory, at its desk. */
function marginHTML() {
  const head = (label, link) => `<div class="m-h"><span class="label">${label}</span>${link || ''}</div>`;
  const go = (tab, label) => `<button class="textlink" type="button" data-goto="${tab}">${label}</button>`;
  const panel = (attrs, inner) => `<section class="panel" ${attrs}>${inner}</section>`;
  const parts = [];
  if (life.beliefs.length) parts.push(panel('data-for="beliefs"', head('Beliefs', go('beliefs', `All ${life.beliefs.length} →`))
    + life.beliefs.map((b) => `<div class="m-item"><div class="text two">${esc(b.text)}</div><div class="strength"><span class="held thin" aria-hidden="true"><i style="width:${Math.round(b.confidence * 100)}%"></i></span><span>held at ${Math.round(b.confidence * 100)}%</span></div></div>`).join('')));
  const made = madeLately();
  if (made.length) parts.push(panel('', head('Made lately')
    + `<div class="m-thumbs">${made.map((f) => `<button class="thumb" type="button" data-pic="${esc(f.picture)}" data-cap="${esc(f.path)}" aria-label="Open ${esc(f.path)}"><img src="${esc(f.picture)}" alt="" loading="lazy"></button>`).join('')}</div>
    <p class="m-cap">${esc(made[0].path.replace(/\.[a-z]+$/i, '').split('/').join(' / '))} · ${when(made[0].at)}</p>`));
  return parts.join('');
}

/* narrow, beside a chat: the margin as a short summary at the top of its life */
function glanceHTML() {
  const line = (attrs, a, b) => `<button class="g" type="button" ${attrs}><span>${a}</span><span>${b}</span></button>`;
  const rows = [];
  if (life.beliefs.length) {
    const held = life.beliefs.map((b) => Math.round(b.confidence * 100)), lo = Math.min(...held), hi = Math.max(...held);
    rows.push(line('data-goto="beliefs"', 'Beliefs', `${life.beliefs.length}, ${held.length === 1 ? 'held' : lo === hi ? 'each held' : 'held'} at ${lo === hi ? `${lo}%` : `${lo} to ${hi}%`}`));
  }
  const made = madeLately()[0];
  if (made) rows.push(line(`data-pic="${esc(made.picture)}" data-cap="${esc(made.path)}"`, 'Made lately', esc(made.path.split('/').pop())));
  return rows.join('');
}

function margin() {
  $('margin').innerHTML = marginHTML();
  $('glance').innerHTML = glanceHTML();
  fit();
}
// the margin stays in view as you read only when all of it fits the window; otherwise it scrolls with the page,
// so nothing at its foot is ever out of reach
function fit() { const m = $('margin'); m.classList.toggle('stick', m.offsetHeight + 72 <= innerHeight); }
addEventListener('resize', fit);

function missing() {
  const who = life.identity;
  $('name').textContent = who.name;
  $('state').textContent = 'No memory found';
  $('verify').innerHTML = '';
  $('tabs').innerHTML = '';
  nav.hidden = true;                           // with no tabs, the empty track would show as a stray dot
  $('body').innerHTML = `<div class="missing"><p>There is no memory at <code>${esc(who.store)}</code> for <code>${esc(who.agentId)}</code>.</p>
    <p>If your agent keeps its memory under another name, start the log with it, for example <code>mnemos log --agent-id claude-code</code>, or set <code>MNEMOS_AGENT_ID</code>.</p></div>`;
}

/* ---------- the track: its marker glides to the open tab; the content trades places as it goes ---------- */

const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
function placeMarker(view, glide) {
  const key = placeOf(view);                   // the marker sits on the place a view belongs to
  const track = $('track'), btn = $('tabs').querySelector(`[data-tab="${key}"]`), marker = $('marker');
  if (!btn) return;
  marker.classList.toggle('still', !glide || reduce);
  const r = btn.getBoundingClientRect(), base = track.getBoundingClientRect();    // fractional pixels, so it fits exactly
  marker.style.width = `${r.width}px`;
  marker.style.transform = `translateX(${r.left - base.left}px)`;
  if (glide) btn.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
}
let leaving = null, then = null;              // then: what to do once the new content is in place
const arrived = () => { if (then) { const f = then; then = null; requestAnimationFrame(f); } };
function transition(apply, from, to) {
  const body = $('body');
  if (reduce) { apply(); arrived(); return; }
  const order = (v) => ROUTES.indexOf(v === 'notes' ? 'you' : v);
  const dir = from === to ? 0 : Math.sign(order(to) - order(from));
  document.documentElement.style.setProperty('--dir', String(dir));
  if (placeOf(from) !== placeOf(to)) {
    for (const b of $('tabs').querySelectorAll('[data-tab]')) b.setAttribute('aria-selected', String(b.dataset.tab === placeOf(to)));
    placeMarker(to, true);
  }
  clearTimeout(leaving);                       // a second click mid-way simply becomes the destination
  body.classList.remove('settle', 'entering');
  body.classList.add('leaving');
  leaving = setTimeout(() => {
    body.classList.remove('leaving');
    body.classList.add('entering');
    apply();
    arrived();
    void body.offsetWidth;                     // the new content starts from its side, then settles
    body.classList.add('settle');
    body.classList.remove('entering');
    setTimeout(() => body.classList.remove('settle'), 560);
  }, 150);
}

/* ---------- live ---------- */

async function look() {
  if (document.hidden && life) return;
  let next;
  try { next = await json('../data/life.json'); } catch { if (life) head(); return; }
  if (life && next.made === life.made) { head(); return; }
  life = next;
  if (life.missing) return missing();
  nav.hidden = false;
  if (life.memory.version !== version) {
    try {
      const m = await json('../data/memories.json');
      mems = m.memories; version = m.version; byId = new Map(mems.map((x, i) => [x.id, i]));
    } catch { /* the next look will try again */ }
  }
  head();
  if (!room) start(); else { room.refresh(); margin(); placeMarker(room.s.tab, false); }
}

function start() {
  room = new Room({
    tabsEl: $('tabs'), bodyEl: $('body'), tabs: TABS, sticky: false,
    ctx: () => ({ who: life.identity, life, mems, byId }),
    hooks: {
      route: (hash) => { history.replaceState(null, '', hash); mark(); placeMarker(room.s.tab, true); },
      // what you write on the page: a reply or a note, sent to `mnemos log` (and on to the memory) as yours
      send: async (request) => {
        const r = await fetch('../act', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) });
        const answer = await r.json().catch(() => ({ error: 'It couldn’t be sent just now.' }));
        if (answer.result) await look();
        return answer;
      },
      // its notes you've read here, so it knows you have
      read: async (ids) => {
        const r = await fetch('../act', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: 'read', note_ids: ids }) });
        if (!r.ok) throw new Error('not marked');
        await look();
      },
      transition,
      picture: (src, cap) => { $('full-img').src = src; $('full-img').alt = cap; $('full-cap').textContent = cap; $('full').showModal(); },
      hour: (id) => {
        then = () => document.querySelector(`.ev[data-hour="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'start' });
        room.go({ tab: 'log' });
      },
    },
  });
  const r = parseRoute(location.hash, ROUTES);
  room.s.tab = r?.tab === 'notes' ? 'you' : r?.tab || 'you'; room.s.memory = r?.memory && byId.has(r.memory) ? r.memory : null;
  mark();
  room.render();
  margin();
  placeMarker(room.s.tab, false);
  document.fonts.ready.then(() => placeMarker(room.s.tab, false));   // the labels' true width arrives with the font
  addEventListener('resize', () => placeMarker(room.s.tab, false));
}

// the page knows which place it's in: the margin sits beside its life only
function mark() { document.body.dataset.tab = room.s.tab; document.body.dataset.place = placeOf(room.s.tab); }

addEventListener('hashchange', () => {
  const r = parseRoute(location.hash, ROUTES);
  if (room && r) room.go({ tab: r.tab === 'notes' ? 'you' : r.tab || room.s.tab, memory: r.memory || null });
});
addEventListener('keydown', (e) => {
  if (e.key === '/' && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || '') && room) {
    e.preventDefault(); room.go({ tab: 'memories' }); requestAnimationFrame(() => $('room-search')?.focus());
  }
});
for (const el of [$('margin'), $('glance')]) el.addEventListener('click', (e) => {
  const pic = e.target.closest('[data-pic]');
  if (pic) { $('full-img').src = pic.dataset.pic; $('full-img').alt = pic.dataset.cap; $('full-cap').textContent = pic.dataset.cap; $('full').showModal(); return; }
  const q = e.target.closest('[data-qkind]');
  if (q) { room.s.qkind = q.dataset.qkind; room.go({ tab: 'questions' }); return; }
  const g = e.target.closest('[data-goto]');
  if (g) room.go({ tab: g.dataset.goto });
});
$('full-close').addEventListener('click', () => $('full').close());
$('full').addEventListener('click', (e) => { if (e.target === $('full')) $('full').close(); });

await look();
setInterval(look, EVERY);
setInterval(() => { if (life && !life.missing) head(); }, 15_000);     // it cools while you read
window.__log = { get room() { return room; }, get life() { return life; }, get count() { return mems.length; } };
