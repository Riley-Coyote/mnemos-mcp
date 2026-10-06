/* The reading room: everything a mind holds, readable and searchable. The log makes it the page, handing it the data
 * (../data/life.json and ../data/memories.json) and a few hooks; a view that opens it as a drawer (sticky) is
 * handed the same, so the views never drift apart.
 *
 *   new Room({ tabsEl, bodyEl, tabs, sticky, ctx, hooks })
 *     ctx()   → { who, life, mems, byId, heat?(id) }   who: the export's identity
 *     hooks   → { hover(id|null), open(id|null), route(hash), mindLink?(id), picture?(src, caption), hour?(id) }
 */

import { esc, at, clock, dayKey, dayName, longDay, shortDay, plural, putTo, question, firstLine, opening, titleOf, signedBy, person,
  forPerson, temperature, tempWord, KIND, ASK, ASK_ORDER, RELATION, trailSentence, modelName, sameModel } from './words.js';

const LABEL = { log: 'Log', memories: 'Memories', beliefs: 'Beliefs', questions: 'Questions', journal: 'Journal', notes: 'Notes', hours: 'Hours' };
const PAGE = 60;

export class Room {
  constructor({ tabsEl, bodyEl, tabs, sticky = false, ctx, hooks = {} }) {
    Object.assign(this, { tabsEl, bodyEl, tabs, sticky, ctx, hooks });
    this.s = { tab: tabs[0], memory: null, query: '', sort: 'newest', filter: 'all', qkind: 'all', shown: PAGE };
    this.whole = new Set();                 // entries opened in full, kept across live redraws
    this.texts = new Map();
    this.bind();
  }

  /* ---------- counts and routes ---------- */

  count(tab) {
    const { life, mems } = this.ctx();
    return { log: null, memories: mems.length, beliefs: life.beliefs.length, questions: life.questions.open,
      journal: life.journal.length, notes: life.notes.length, hours: life.hours.length }[tab];
  }
  hash() { return this.s.memory ? `#read/memory/${this.s.memory}` : `#read/${this.s.tab}`; }
  go({ tab = this.s.tab, memory = null } = {}, keepPage = false) {
    const from = this.s.tab, changed = tab !== this.s.tab || memory !== this.s.memory;
    const apply = () => {
      this.s.tab = tab; this.s.memory = memory;
      if (!keepPage) this.s.shown = PAGE;
      this.render(changed);
      this.hooks.open?.(memory);
      this.hooks.route?.(this.hash());
    };
    // a page may choreograph the change (the log's marker glides and its content trades places); otherwise, at once
    if (changed && this.hooks.transition) this.hooks.transition(apply, from, tab); else apply();
  }

  /* ---------- drawing ---------- */

  render(toTop = false) {
    this.tabsEl.innerHTML = this.tabs.map((k) => {
      const n = this.count(k);
      return `<button class="tab" role="tab" data-tab="${k}" aria-selected="${this.s.tab === k}">${LABEL[k]}${n == null ? '' : `<small>${n.toLocaleString('en-US')}</small>`}</button>`;
    }).join('');
    const { byId } = this.ctx();
    const open = this.s.memory && byId.has(this.s.memory);
    const scroller = this.scroller();
    const top = scroller.scrollTop;
    // a live redraw never takes the search box away from someone typing in it
    const typing = document.activeElement?.id === 'room-search' ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
    this.bodyEl.innerHTML = open ? this.memoryHTML(this.s.memory)
      : { log: () => this.logHTML(), memories: () => this.memoriesHTML(), beliefs: () => this.beliefsHTML(), questions: () => this.questionsHTML(),
        journal: () => this.journalHTML(), notes: () => this.notesHTML(), hours: () => this.hoursHTML() }[this.s.tab]();
    this.restoreOpen();
    if (toTop) this.toTop(); else scroller.scrollTop = top;
    const search = this.bodyEl.querySelector('#room-search');
    if (typing && search) { search.focus({ preventScroll: true }); search.setSelectionRange(...typing); }
    const more = this.bodyEl.querySelector('.more-rows');
    if (more) new IntersectionObserver(([e], o) => { if (e.isIntersecting) { o.disconnect(); this.s.shown += 80; this.render(); } }, { root: this.sticky ? this.bodyEl : null, rootMargin: '400px' }).observe(more);
  }
  scroller() { return this.sticky ? this.bodyEl : document.scrollingElement; }
  toTop() {
    if (this.sticky) { this.bodyEl.scrollTop = 0; return; }
    const y = this.tabsEl.getBoundingClientRect().top + scrollY - 8;
    if (scrollY > y) scrollTo({ top: y });
  }
  refresh() { this.render(); }

  /* the folded text of a long entry, with its button; the whole text is kept for the button */
  own(id, text, cls = 'text', long = 520) {
    this.texts.set(id, text);
    const short = opening(text, long), folded = short.length < text.length, isOpen = this.whole.has(id);
    return `<div class="${cls}" data-text="${esc(id)}">${esc(folded && !isOpen ? short : text)}</div>`
      + (folded ? `<button class="fold" type="button" data-fold="${esc(id)}" aria-expanded="${isOpen}">${isOpen ? 'Show less' : 'Read the whole entry'}</button>` : '');
  }

  /* a journal entry: its first sentence as its title, in the serif; the rest, folded when long, in the sans */
  entry(id, text, long = 520) {
    const { title, body } = titleOf(text);
    return `<div class="t-own">${esc(title)}</div>${body ? this.own(id, body, 'text', long) : ''}`;
  }

  /* ---------- the log: a mind's days ---------- */

  logItems() {
    const { life, mems } = this.ctx();
    const items = [];
    for (const h of life.hours) items.push({ t: h.end || h.start, type: 'hour', h });
    for (const e of life.journal) if (!e.hour) items.push({ t: e.at, type: 'journal', e });
    for (const n of life.notes) if (!n.hour) items.push({ t: n.at, type: 'note', n });
    for (const l of life.handoffs) items.push({ t: l.at, type: 'left', l });
    for (const a of life.questions.answered) items.push({ t: a.at, type: 'answer', a });
    for (const b of life.beliefs) for (const x of b.history || []) if (x.at) items.push({ t: x.at, type: 'belief', b, x });
    const formed = new Map();               // memories formed, gathered by day
    for (const m of mems) {
      const k = dayKey(at(m.born));
      if (!formed.has(k)) formed.set(k, []);
      formed.get(k).push(m);
    }
    for (const list of formed.values()) items.push({ t: list[list.length - 1].born, type: 'formed', list });
    return items.filter((i) => i.t).sort((a, b) => Date.parse(b.t) - Date.parse(a.t));
  }
  logHTML() {
    const items = this.logItems();
    if (!items.length) return '<p class="empty">Nothing yet. As it works with you, learns, writes and rests, its days gather here.</p>';
    const days = [];
    for (const it of items.slice(0, this.s.shown)) {
      const k = dayKey(at(it.t));
      if (!days.length || days[days.length - 1].k !== k) days.push({ k, d: at(it.t), items: [] });
      days[days.length - 1].items.push(it);
    }
    return days.map((day) => {
      const name = dayName(day.d), date = longDay(day.d);
      return `<section class="day"><h3 class="dayh"><span>${esc(name)}</span>${name === date ? '' : `<span class="date">${esc(date)}</span>`}</h3>${day.items.map((it) => this.eventHTML(it)).join('')}</section>`;
    }).join('') + (items.length > this.s.shown ? '<div class="more-rows"></div>' : '');
  }

  /* One event: its time in the rail, a small label naming what kind of thing happened, then the thing. A quiet hour,
     the mind's own time, is a raised object; everything else is a quiet line on the page. Long writing opens folded. */
  eventHTML(it) {
    const { who, life } = this.ctx();
    const t = `<div class="t">${clock(at(it.t))}</div>`;
    const kind = (label, right = '') => `<div class="kd"><span>${label}</span>${right}</div>`;
    const SHORT = 300;
    if (it.type === 'hour') {
      const h = it.h, k = temperature(h);
      const pics = h.made.map((p) => life.studio.find((f) => f.path === p)).filter((f) => f && f.picture);
      const ok = h.status === 'done' && !h.reason;
      const facts = [
        h.modelName ? (h.model && who.model && !sameModel(h.model, who.model) ? `<span class="flag">ran as ${esc(h.modelName)}; nothing it wrote was kept</span>` : `ran as ${esc(h.modelName)}`) : null,
        h.practice ? (h.check === 'rows' ? (h.untouched === false ? '<span class="flag">left something in the real memory</span>' : 'real memory untouched') : 'checked the older way') : null,
        h.refused.length ? `<span class="flag">refused: ${[...new Set(h.refused)].map(esc).join(', ')}</span>` : 'nothing refused',
        ok ? null : `<span class="flag">${esc(h.reason || h.status)}</span>`,
      ].filter(Boolean);
      const temp = `<span class="temp" style="--k:${Math.max(0, Math.min(1, k)).toFixed(3)}"><i></i>${tempWord(k, h).toLowerCase()}</span>`;
      const entries = [...h.journal].reverse();
      return `<article class="ev hour" data-hour="${esc(h.id)}">${t}<div class="b">
        ${kind(KIND[h.kind] || esc(h.kind), temp)}
        <div class="line">${clock(at(h.start))} to ${clock(at(h.end))}${h.minutes != null ? ` · ${h.minutes < 1 ? 'under a minute' : `${Math.round(h.minutes * 10) / 10} minutes`}` : ''}${h.practice ? ' · practice, on a copy of its memory' : ''}</div>
        <div class="sub">${esc(trailSentence(h))}</div>
        ${pics.length ? `<div class="thumbs">${pics.map((f) => `<button class="thumb" type="button" data-pic="${esc(f.picture)}" data-cap="${esc(f.path)}" aria-label="Open ${esc(f.path)}"><img src="${esc(f.picture)}" alt="" loading="lazy"></button>`).join('')}</div>` : ''}
        ${entries.map((e) => `<div class="inner"><div class="kd small">Its journal${e.mood ? ` · ${esc(e.mood)}` : ''}</div>${this.entry(e.id, e.text, SHORT)}</div>`).join('')}
        ${h.notes.map((n) => `<div class="inner"><div class="kd small">A note ${esc(forPerson(who))}${h.practice ? ', written in practice' : ''}</div>${this.own(n.id, n.text, 'text note', SHORT)}</div>`).join('')}
        <div class="facts">${facts.map((f) => `<span>${f}</span>`).join('')}</div></div></article>`;
    }
    if (it.type === 'journal') {
      const e = it.e;
      return `<div class="ev">${t}<div class="b">${kind('Journal', e.mood ? `<span class="aside">${esc(e.mood)}</span>` : '')}${this.entry(e.id, e.text, SHORT)}</div></div>`;
    }
    if (it.type === 'note') {
      const n = it.n, mine = n.author === 'agent';
      return `<div class="ev">${t}<div class="b">${kind(mine ? `A note ${esc(forPerson(who))}` : `From ${esc(person(who))}`, mine ? `<span class="aside">${n.read ? 'read' : 'not yet read'}</span>` : '')}${this.own(n.id, n.text, 'text note', SHORT)}</div></div>`;
    }
    if (it.type === 'left') {
      // its notes often open with a signature line ("Left by …, date, session …"); preview what comes after it
      const l = it.l, lines = l.text.split('\n').filter((x) => x.trim());
      const lead = lines.length > 1 && /^left by /i.test(lines[0]) ? lines.slice(1).join('\n') : l.text;
      return `<div class="ev slim">${t}<div class="b">${kind('Note to itself', l.model && !sameModel(l.model, who.model) ? `<span class="aside">signed ${esc(modelName(l.model))}</span>` : '')}
        <div class="sub one">${esc(firstLine(lead, 200))}</div>
        <details data-key="left-${esc(l.at)}"><summary>Read it</summary><div class="text plain">${esc(l.text)}</div></details></div></div>`;
    }
    if (it.type === 'answer') {
      const a = it.a;
      return `<div class="ev">${t}<div class="b">${kind('Answered its memory')}<div class="qline">${esc(question(a.prompt))}</div><div class="text note">${esc(a.answer)}</div></div></div>`;
    }
    if (it.type === 'belief') {
      const { b, x } = it, up = (x.to ?? 0) > (x.from ?? 0);
      return `<div class="ev">${t}<div class="b">${kind('Belief', `<span class="aside">${up ? 'held more firmly' : 'held less firmly'} · ${Math.round((x.from ?? 0) * 100)}% → ${Math.round((x.to ?? 0) * 100)}%</span>`)}<div class="text clamp2">${esc(b.text)}</div></div></div>`;
    }
    if (it.type === 'formed') {
      const list = it.list;
      const rows = [...list].reverse().slice(0, 12).map((m) => `<li><button class="rowb" data-mem="${esc(m.id)}"><div class="meta"><span>${clock(at(m.born))}</span>${m.lesson ? '<span class="k2">a lesson</span>' : ''}</div><div class="words">${esc(m.content)}</div></button></li>`).join('');
      return `<div class="ev slim">${t}<div class="b">${kind('Memories')}<div class="sub one">Formed ${plural(list.length, 'memory', 'memories')}</div>
        <details data-key="formed-${esc(list[0].born)}"><summary>${list.length === 1 ? 'Read it' : 'Read them'}</summary><ul class="rows">${rows}</ul>${list.length > 12 ? `<p class="count">and ${list.length - 12} more, in Memories</p>` : ''}</details></div></div>`;
    }
    return '';
  }

  /* ---------- memories ---------- */

  list() {
    const { mems } = this.ctx(), heat = this.ctx().heat;
    const q = this.s.query.trim().toLowerCase(), f = this.s.filter, s = this.s.sort;
    let out = mems.filter((m) => f === 'all' || (f === 'lessons' ? m.lesson : f === 'standing' ? m.standing : f === 'asked' ? m.asked
      : f === 'quiet' ? m.state === 'dormant' : f === 'warm' ? heat && heat(m.id) > 0.05 : f === 'colleagues' ? m.model && !sameModel(m.model, this.ctx().who.model) : true));
    if (q) out = out.filter((m) => (m.content + ' ' + (m.impact || '')).toLowerCase().includes(q));
    const t = (m) => Date.parse(m.born);
    return out.sort((a, b) => s === 'recalled' ? b.recalls - a.recalls || t(b) - t(a) : s === 'connected' ? b.ties.length - a.ties.length
      : s === 'easiest' ? b.acc - a.acc : s === 'oldest' ? t(a) - t(b) : t(b) - t(a));
  }
  row(m) {
    const heat = this.ctx().heat, { who } = this.ctx();
    const tags = [m.lesson ? 'a lesson' : null, m.standing ? 'standing' : null, m.asked ? 'asked about' : null, m.state === 'dormant' ? 'gone quiet' : null,
      m.model && !sameModel(m.model, who.model) ? modelName(m.model) : null].filter(Boolean);
    return `<li><button class="rowb" data-mem="${esc(m.id)}"><div class="meta"><span>${shortDay(at(m.born))}</span>${tags.map((x) => `<span class="k2">${esc(x)}</span>`).join('')}${heat && heat(m.id) > 0.05 ? '<span class="warm">warm from its hours</span>' : ''}${m.recalls ? `<span>recalled ${m.recalls}×</span>` : ''}</div>
      <div class="words">${esc(m.content)}</div></button></li>`;
  }
  memoriesHTML() {
    const { mems } = this.ctx(), all = this.list(), heat = this.ctx().heat;
    const chip = (g, v, label) => `<button class="chip" data-${g}="${v}" aria-pressed="${this.s[g] === v}">${label}</button>`;
    const colleagues = mems.some((m) => m.model && !sameModel(m.model, this.ctx().who.model));
    return `<div class="tools${this.sticky ? ' stick' : ''}"><input class="search" id="room-search" type="search" placeholder="Search its memory, in its own words" value="${esc(this.s.query)}" aria-label="Search its memory">
      <div class="chips">${chip('filter', 'all', 'All')}${heat ? chip('filter', 'warm', 'Warm from its hours') : ''}${chip('filter', 'lessons', 'Lessons')}${chip('filter', 'standing', 'Standing')}${chip('filter', 'asked', 'Asked about')}${chip('filter', 'quiet', 'Gone quiet')}${colleagues ? chip('filter', 'colleagues', 'By colleagues') : ''}</div>
      <div class="chips"><span class="sep">Order</span>${chip('sort', 'newest', 'Newest')}${chip('sort', 'oldest', 'Oldest')}${chip('sort', 'recalled', 'Most recalled')}${chip('sort', 'connected', 'Most connected')}${chip('sort', 'easiest', 'Easiest to reach')}</div>
      <div class="count">${all.length === mems.length ? `All ${plural(mems.length, 'memory', 'memories')}` : `${plural(all.length, 'memory', 'memories')} of ${mems.length.toLocaleString('en-US')}`}</div></div>
      <ul class="rows">${all.slice(0, this.s.shown).map((m) => this.row(m)).join('')}</ul>${all.length > this.s.shown ? '<div class="more-rows"></div>' : ''}
      ${mems.length ? (all.length ? '' : '<p class="empty">Nothing in its memory matches that.</p>') : '<p class="empty">Its memory is empty.</p>'}`;
  }
  memoryHTML(id) {
    const { who, life, mems, byId } = this.ctx(), m = mems[byId.get(id)];
    const d = at(m.born);
    const asks = life.questions.asked.filter((q) => q.about === id), answers = life.questions.answered.filter((q) => q.about === id);
    const beliefs = life.beliefs.filter((b) => (b.supports || []).includes(id));
    const hours = life.hours.filter((h) => { const t = h.trail || {}; return [...(t.woke || []), ...(t.waiting || []), ...(t.reached || [])].includes(id); });
    const sign = [signedBy(m, who), m.lesson ? 'a lesson' : null, m.standing ? 'standing: how it works every session' : null,
      m.recalls ? `came back in logged recall ${plural(m.recalls, 'time')}` : null, `tied to ${plural(m.ties.length, 'other memory', 'other memories')}`,
      m.state === 'dormant' ? 'gone quiet' : null].filter(Boolean).join(' · ');
    const link = this.hooks.mindLink?.(id);
    return `<div class="detail"><button class="back" data-back="1">← ${LABEL[this.s.tab] === 'Memories' ? 'All memories' : `Back to ${LABEL[this.s.tab].toLowerCase()}`}</button>
      <div class="meta">${longDay(d)}, ${clock(d)} · ${esc(sign)}</div>
      <div class="words">${esc(m.content)}</div>
      ${m.impact ? `<div class="changed"><span class="label">What it changed, in its words</span><p>${esc(m.impact)}</p></div>` : ''}
      ${link ? `<a class="textlink mindlink" href="${esc(link)}">See it in the mind →</a>` : ''}
      ${beliefs.length ? `<h3>A belief rests on it</h3><ul class="lines">${beliefs.map((b) => `<li><span class="a">${esc(b.text)}</span><span class="m">held at ${Math.round(b.confidence * 100)}%</span></li>`).join('')}</ul>` : ''}
      ${hours.length ? `<h3>In its hours</h3><ul class="lines">${hours.map((h) => { const t = h.trail || {};
        const how = (t.reached || []).includes(id) ? 'reached for it' : (t.waiting || []).includes(id) ? 'found it waiting, as a question' : 'woke with it in hand';
        return `<li>${KIND[h.kind] || esc(h.kind)}, ${shortDay(at(h.start))} at ${clock(at(h.start))}: ${how}${h.practice ? ' (practice)' : ''}</li>`; }).join('')}</ul>` : ''}
      ${asks.length ? `<h3>What its memory asks about it</h3><ul class="lines">${asks.map((q) => `<li>${esc(question(q.prompt))}<span class="m">${putTo(q.shown)}</span></li>`).join('')}</ul>` : ''}
      ${answers.length ? `<h3>Its answers</h3><ul class="lines">${answers.map((q) => `<li>${esc(question(q.prompt))}<span class="a">${esc(q.answer)}</span></li>`).join('')}</ul>` : ''}
      ${m.ties.length ? `<h3>Tied to</h3><ul class="rows">${m.ties.slice(0, 24).map(([tid, rel]) => { const t = mems[byId.get(tid)]; if (!t) return '';
        return `<li><button class="rowb" data-mem="${esc(tid)}"><div class="meta"><span>${shortDay(at(t.born))}</span><span class="k">${RELATION[rel] || esc(rel)}</span></div><div class="words">${esc(t.content)}</div></button></li>`; }).join('')}</ul>${m.ties.length > 24 ? `<p class="count">and ${m.ties.length - 24} more</p>` : ''}` : ''}
    </div>`;
  }

  /* ---------- beliefs, questions, journal, notes, hours ---------- */

  beliefsHTML() {
    const { who, life, mems, byId } = this.ctx();
    if (!life.beliefs.length) return '<p class="empty">No beliefs yet. One forms only when it says yes to a question its memory asks.</p>';
    return '<p class="note-k">It holds its beliefs in its own words, and lightly. Each rests on a memory you can open.</p>' + life.beliefs.map((b) => {
      const id = (b.supports || []).find((s) => byId.has(s)), m = id ? mems[byId.get(id)] : null;
      const h = b.history || [], down = h.filter((x) => (x.to ?? 0) < (x.from ?? 0)).length, up = h.filter((x) => (x.to ?? 0) > (x.from ?? 0)).length;
      const rests = !m ? 'resting on no memory in view' : m.model && !sameModel(m.model, who.model) ? `rests on a memory ${modelName(m.model)} wrote, a colleague` : 'rests on a memory of its own';
      return `<div class="belief"><div class="words">${esc(b.text)}</div><div class="held" aria-hidden="true"><i style="width:${Math.round(b.confidence * 100)}%"></i></div>
        <div class="sign">Held at ${Math.round(b.confidence * 100)}% · ${esc(rests)}${down ? ` · lowered ${plural(down, 'time')}${up ? ', then raised again' : ''}` : ''}</div>
        ${m ? `<ul class="rows"><li><button class="rowb" data-mem="${esc(m.id)}"><div class="meta"><span>The memory it rests on</span></div><div class="words">${esc(m.content)}</div></button></li></ul>` : ''}</div>`;
    }).join('');
  }
  questionsHTML() {
    const { life, byId } = this.ctx(), Q = life.questions;
    if (!Q.open && !Q.answered.length) return '<p class="empty">Its memory isn’t asking it anything right now.</p>';
    const kinds = Object.entries(Q.byKind || {}).sort((a, b) => (ASK_ORDER[a[0]] ?? 9) - (ASK_ORDER[b[0]] ?? 9));
    // the questions grounded in meaning first; the ones counted from recurring words after them
    const list = Q.asked.filter((q) => this.s.qkind === 'all' || q.kind === this.s.qkind)
      .sort((a, b) => (ASK_ORDER[a.kind] ?? 9) - (ASK_ORDER[b.kind] ?? 9) || Date.parse(b.at) - Date.parse(a.at));
    const rows = list.slice(0, this.s.shown).map((q) => `<li><button class="rowb" ${byId.has(q.about) ? `data-mem="${esc(q.about)}"` : 'disabled'}>
      <div class="meta"><span class="k">${(ASK[q.kind] || [q.kind])[0]}</span><span>${putTo(q.shown)}</span><span>${shortDay(at(q.at))}</span></div>
      <div class="q">${esc(question(q.prompt))}</div>${q.excerpt ? `<div class="ex">${esc(q.excerpt)}</div>` : ''}</button></li>`).join('');
    const answered = Q.answered.map((a) => `<li><button class="rowb" ${byId.has(a.about) ? `data-mem="${esc(a.about)}"` : 'disabled'}>
      <div class="meta"><span class="k">${(ASK[a.kind] || [a.kind])[0]}</span><span>answered ${shortDay(at(a.at))}</span></div>
      <div class="q">${esc(question(a.prompt))}</div><div class="ans">${esc(a.answer)}</div></button></li>`).join('');
    return `<div class="kinds" role="group" aria-label="Kinds of question">${kinds.map(([k, n]) => `<button class="kindb" data-qkind="${k}" aria-pressed="${this.s.qkind === k}"><b>${n}</b><span>${(ASK[k] || [k])[0]}</span></button>`).join('')}</div>
      <p class="note-k">${this.s.qkind !== 'all' && ASK[this.s.qkind] ? esc(ASK[this.s.qkind][1]) + ' ' : ''}Open a question to read the memory it’s about.${this.s.qkind !== 'all' ? ' <button class="chip" data-qkind="all">Show every kind</button>' : ''}</p>
      <ul class="rows" style="margin-top:var(--s3)">${rows}</ul>${list.length > this.s.shown ? '<div class="more-rows"></div>' : ''}
      ${answered ? `<span class="label sub-h">Answered, in its words</span><ul class="rows" style="margin-top:var(--s2)">${answered}</ul>` : ''}`;
  }
  journalHTML() {
    const { life } = this.ctx();
    if (!life.journal.length) return '<p class="empty">Its journal is empty. It writes there only when something’s there.</p>';
    return life.journal.map((e) => `<div class="jentry"><div class="meta"><span>${longDay(at(e.at))}, ${clock(at(e.at))}</span><span>${e.written === 'between_sessions' ? 'written between conversations' : 'written in conversation'}</span>${e.mood ? `<span>mood, in its words: ${esc(e.mood)}</span>` : ''}</div>
      ${this.entry(e.id, e.text)}</div>`).join('');
  }
  notesHTML() {
    const { who, life } = this.ctx();
    if (!life.notes.length) return `<p class="empty">No notes yet. It leaves one only when it passes the room test: something it would say if ${esc(person(who) === 'you' ? 'you' : person(who))} walked in right now. Notes written in practice hours stay in their copies; you’ll find them with their hour in the log.</p>`;
    return life.notes.map((n) => `<div class="jentry"><div class="meta"><span>${n.author === 'agent' ? `To ${esc(person(who))}` : `From ${esc(person(who))}`}</span><span>${longDay(at(n.at))}, ${clock(at(n.at))}</span>${n.kind ? `<span>${esc(n.kind)}</span>` : ''}${n.author === 'agent' ? `<span>${n.read ? 'read' : 'not yet read'}</span>` : ''}</div>
      ${this.own(n.id, n.text, 'text note')}</div>`).join('');
  }
  hoursHTML() {
    const { life } = this.ctx();
    if (!life.hours.length) return '<p class="empty">No quiet hour has run yet. When hours are turned on, each one appears here as soon as it ends.</p>';
    return `<ul class="rows">${life.hours.map((h) => { const s = at(h.start), k = temperature(h);
      return `<li><button class="rowb" data-hour="${esc(h.id)}"><div class="meta"><span>${shortDay(s)}, ${clock(s)}</span><span class="k">${KIND[h.kind] || esc(h.kind)}</span><span>${h.practice ? 'practice' : 'real'}</span><span class="${k > 0.06 ? 'warm' : ''}">${tempWord(k, h).toLowerCase()}</span></div>
        <div class="q">${esc(trailSentence(h))}</div>${h.journal.length ? `<div class="ex">${esc(firstLine(h.journal[h.journal.length - 1].text, 200))}</div>` : ''}</button></li>`; }).join('')}</ul>`;
  }

  /* ---------- events ---------- */

  bind() {
    this.tabsEl.addEventListener('click', (e) => { const t = e.target.closest('[data-tab]'); if (t) { this.s.qkind = 'all'; this.go({ tab: t.dataset.tab }); } });
    const body = this.bodyEl;
    body.addEventListener('click', (e) => {
      const fold = e.target.closest('[data-fold]');
      if (fold) {
        const id = fold.dataset.fold, open = !this.whole.has(id);
        if (open) this.whole.add(id); else this.whole.delete(id);
        const text = this.texts.get(id) || '';
        fold.previousElementSibling.textContent = open ? text : opening(text);
        fold.setAttribute('aria-expanded', open); fold.textContent = open ? 'Show less' : 'Read the whole entry';
        return;
      }
      const pic = e.target.closest('[data-pic]'); if (pic) return this.hooks.picture?.(pic.dataset.pic, pic.dataset.cap);
      const m = e.target.closest('[data-mem]'); if (m && !m.disabled) return this.go({ tab: this.s.tab === 'log' ? 'log' : this.s.tab, memory: m.dataset.mem });
      if (e.target.closest('[data-back]')) return this.go({ tab: this.s.tab, memory: null });
      const f = e.target.closest('[data-filter]'); if (f) { this.s.filter = f.dataset.filter; this.s.shown = PAGE; return this.render(); }
      const s = e.target.closest('[data-sort]'); if (s) { this.s.sort = s.dataset.sort; this.s.shown = PAGE; return this.render(); }
      const k = e.target.closest('[data-qkind]'); if (k) { this.s.qkind = this.s.qkind === k.dataset.qkind ? 'all' : k.dataset.qkind; this.s.shown = PAGE; return this.render(); }
      const h = e.target.closest('[data-hour]'); if (h && this.hooks.hour) return this.hooks.hour(h.dataset.hour);
    });
    body.addEventListener('input', (e) => {
      if (e.target.id !== 'room-search') return;
      this.s.query = e.target.value; this.s.shown = PAGE;
      this.render();
    });
    // keep open disclosures open across the live redraws
    body.addEventListener('toggle', (e) => { const d = e.target; if (d.dataset?.key) { if (d.open) this.whole.add(d.dataset.key); else this.whole.delete(d.dataset.key); } }, true);
    const touch = (e) => { const m = e.target.closest('[data-mem]'); this.hooks.hover?.(m ? m.dataset.mem : null); };
    body.addEventListener('pointerover', touch);
    body.addEventListener('focusin', touch);
    body.addEventListener('pointerleave', () => this.hooks.hover?.(null));
  }
  restoreOpen() { for (const d of this.bodyEl.querySelectorAll('details[data-key]')) if (this.whole.has(d.dataset.key)) d.open = true; }
}

/* one route for both views: #read/<tab> or #read/memory/<id> */
export function parseRoute(hash, tabs) {
  const m = (hash || '').match(/^#read\/(memory\/(.+)|(\w+))$/);
  if (!m) return null;
  if (m[2]) return { memory: decodeURIComponent(m[2]) };
  return tabs.includes(m[3]) ? { tab: m[3] } : null;
}
