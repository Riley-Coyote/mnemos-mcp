/* The log. Reads ../data/life.json (small, every 20 seconds) and ../data/memories.json (when the memory changes), both
 * made read-only on request by `mnemos log` for whichever mind it was started with. Nothing here writes anywhere. */

import { Room, parseRoute } from '../shared/room.js';
import { esc, at, ago, clock, dayName, plural, question, firstLine, temperature, tempWord, KIND, ASK, ASK_ORDER, person, sameModel, modelName } from '../shared/words.js';

const $ = (id) => document.getElementById(id);
const nav = document.querySelector('.nav');
const EVERY = 20_000;
const STALE_AFTER = 3 * 60_000;              // every read is fresh; three minutes without one means `mnemos log` stopped
const TABS = ['log', 'memories', 'beliefs', 'questions', 'journal', 'notes', 'hours'];

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

/* ---------- the margin: its state beside its story ---------- */

const notesFor = () => life.notes.filter((n) => n.author === 'agent');
const practiceNotes = () => life.hours.filter((h) => h.practice && h.notes.length);
const carrying = () => {
  const l = life.handoffs[0];
  if (!l) return null;
  // its notes often open with a signature line ("Left by …, date, session …"); show what comes after it
  const lines = l.text.split('\n').filter((x) => x.trim());
  return { ...l, lead: lines.length > 1 && /^left by /i.test(lines[0]) ? lines.slice(1).join('\n') : l.text };
};
const madeLately = () => life.studio.filter((f) => f.picture).slice(0, 3);
const when = (iso) => { const d = at(iso); return `${dayName(d)}, ${clock(d)}`; };

function marginHTML() {
  const who = life.identity, Q = life.questions, notes = notesFor(), practice = practiceNotes();
  const head = (label, link) => `<div class="m-h"><span class="label">${label}</span>${link || ''}</div>`;
  const go = (tab, label) => `<button class="textlink" type="button" data-goto="${tab}">${label}</button>`;
  const panel = (attrs, inner) => `<section class="panel" ${attrs}>${inner}</section>`;
  const parts = [];
  parts.push(panel('data-for="notes"', head(who.person ? `For ${esc(who.person)}` : 'For you', notes.length ? go('notes', `All ${notes.length} →`) : '')
    + (notes.length ? notes.slice(0, 2).map((n) => `<div class="m-item"><div class="text note">${esc(n.text)}</div><div class="by">${when(n.at)} · ${n.read ? 'read' : 'not yet read'}</div></div>`).join('')
      : `<p class="m-empty">None yet: it leaves one only when it would say it if ${esc(person(who))} walked in.${practice.length ? ` ${practice.length === 1 ? 'One from practice is' : `${practice.length} from practice are`} in the log.` : ''}</p>`)));
  if (life.beliefs.length) parts.push(panel('data-for="beliefs"', head('Beliefs', go('beliefs', `All ${life.beliefs.length} →`))
    + life.beliefs.map((b) => `<div class="m-item"><div class="text two">${esc(b.text)}</div><div class="strength"><span class="held thin" aria-hidden="true"><i style="width:${Math.round(b.confidence * 100)}%"></i></span><span>held at ${Math.round(b.confidence * 100)}%</span></div></div>`).join('')));
  if (Q.open || Q.answered.length) {
    const kinds = Object.entries(Q.byKind).sort((a, b) => (ASK_ORDER[a[0]] ?? 9) - (ASK_ORDER[b[0]] ?? 9));
    const latest = Q.answered[0];
    parts.push(panel('data-for="questions"', head('Its memory asks', go('questions', `All ${Q.open.toLocaleString('en-US')} →`))
      + `<div class="m-counts">${kinds.map(([k, n]) => `<button class="m-count" type="button" data-qkind="${k}" aria-label="${n} questions: ${(ASK[k] || [k])[0]}"><b>${n.toLocaleString('en-US')}</b><span>${(ASK[k] || [k])[0]}</span></button>`).join('')}</div>`
      + (latest ? `<div class="m-item"><div class="q">Its latest answer · ${when(latest.at)}</div><div class="ask">${esc(question(latest.prompt))}</div><div class="a">${esc(latest.answer)}</div></div>` : '')));
  }
  const c = carrying();
  if (c) parts.push(panel('', head('Carrying forward')
    + `<div class="m-item"><div class="q">The note it left itself · ${when(c.at)}</div><div class="lead" style="margin-top:4px">${esc(c.lead)}</div>
      <details data-key="carrying"><summary>Read it</summary><div class="plain">${esc(c.text)}</div></details></div>`));
  const made = madeLately();
  if (made.length) parts.push(panel('', head('Made lately')
    + `<div class="m-thumbs">${made.map((f) => `<button class="thumb" type="button" data-pic="${esc(f.picture)}" data-cap="${esc(f.path)}" aria-label="Open ${esc(f.path)}"><img src="${esc(f.picture)}" alt="" loading="lazy"></button>`).join('')}</div>
    <p class="m-cap">${esc(made[0].path.replace(/\.[a-z]+$/i, '').split('/').join(' / '))} · ${when(made[0].at)}</p>`));
  return parts.join('');
}

function glanceHTML() {
  const who = life.identity, Q = life.questions, notes = notesFor(), unread = notes.filter((n) => !n.read).length;
  const line = (attrs, a, b) => `<button class="g" type="button" ${attrs}><span>${a}</span><span>${b}</span></button>`;
  const rows = [line('data-goto="notes"', who.person ? `For ${esc(who.person)}` : 'For you', notes.length ? (unread ? `${unread} not yet read` : plural(notes.length, 'note')) : 'no notes yet')];
  if (life.beliefs.length) rows.push(line('data-goto="beliefs"', 'Beliefs', `${life.beliefs.length}, held at ${life.beliefs.map((b) => `${Math.round(b.confidence * 100)}%`).join(', ')}`));
  if (Q.open) rows.push(line('data-goto="questions"', 'What its memory asks', `${Q.open.toLocaleString('en-US')} open${Q.byKind.contradiction ? ` · ${Q.byKind.contradiction} ${Q.byKind.contradiction === 1 ? 'contradiction' : 'contradictions'}` : ''}`));
  const made = madeLately()[0];
  if (made) rows.push(line(`data-pic="${esc(made.picture)}" data-cap="${esc(made.path)}"`, 'Made lately', esc(made.path.split('/').pop())));
  return rows.join('');
}

function margin() {
  const m = $('margin'), keep = m.querySelector('details[open]') ? true : false;
  m.innerHTML = marginHTML();
  if (keep) m.querySelector('details[data-key="carrying"]')?.setAttribute('open', '');
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
function placeMarker(key, glide) {
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
  const dir = from === to ? 0 : Math.sign(TABS.indexOf(to) - TABS.indexOf(from));
  document.documentElement.style.setProperty('--dir', String(dir));
  if (from !== to) {
    for (const b of $('tabs').querySelectorAll('[data-tab]')) b.setAttribute('aria-selected', String(b.dataset.tab === to));
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
      route: (hash) => { history.replaceState(null, '', hash); document.body.dataset.tab = room.s.tab; placeMarker(room.s.tab, true); },
      transition,
      picture: (src, cap) => { $('full-img').src = src; $('full-img').alt = cap; $('full-cap').textContent = cap; $('full').showModal(); },
      hour: (id) => {
        then = () => document.querySelector(`.ev[data-hour="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'start' });
        room.go({ tab: 'log' });
      },
    },
  });
  const r = parseRoute(location.hash, TABS);
  room.s.tab = r?.tab || 'log'; room.s.memory = r?.memory && byId.has(r.memory) ? r.memory : null;
  document.body.dataset.tab = room.s.tab;
  room.render();
  margin();
  placeMarker(room.s.tab, false);
  document.fonts.ready.then(() => placeMarker(room.s.tab, false));   // the labels' true width arrives with the font
  addEventListener('resize', () => placeMarker(room.s.tab, false));
}

addEventListener('hashchange', () => {
  const r = parseRoute(location.hash, TABS);
  if (room && r) room.go({ tab: r.tab || room.s.tab, memory: r.memory || null });
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
