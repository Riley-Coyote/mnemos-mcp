/* The reading room: everything a mind holds, readable and searchable. The log makes it the page, handing it the data
 * (../data/life.json and ../data/memories.json) and a few hooks; a view that opens it as a drawer (sticky) is
 * handed the same, so the views never drift apart.
 *
 *   new Room({ tabsEl, bodyEl, tabs, sticky, ctx, hooks })
 *     ctx()   → { who, life, mems, byId, heat?(id) }   who: the export's identity
 *     hooks   → { hover(id|null), open(id|null), route(hash), mindLink?(id), picture?(src, caption), hour?(id), top?(), scroller?(), pane?, leave?() }
 */

import { SHARED, esc, at, clock, dayKey, dayName, longDay, shortDay, plural, putTo, question, firstLine, opening, titleOf, signedBy, person,
  forPerson, temperature, tempWord, KIND, ASK, ASK_ORDER, RELATION, trailSentence, modelName, sameModel } from './words.js';

import { telling, setTelling, canTell, refused } from './tell.js';
import { herbariumOf, lifeOf, lifeWords, mountLife } from './specimens.js';

const LABEL = { shared: SHARED.title, log: 'Log', memories: 'Memories', beliefs: 'Beliefs', questions: 'Questions', journal: 'Journal', notes: 'Notes', hours: 'Hours', settings: 'Settings' };
const PAGE = 60;
const SEEN_AFTER = 1200;                  // a note of its own is read once it has stayed on your screen this long

export class Room {
  constructor({ tabsEl, bodyEl, tabs, sticky = false, ctx, hooks = {} }) {
    Object.assign(this, { tabsEl, bodyEl, tabs, sticky, ctx, hooks });
    this.s = { tab: tabs[0], memory: null, query: '', sort: 'newest', filter: 'all', qkind: 'all', shown: PAGE };
    this.whole = new Set();                 // entries opened in full, kept across live redraws
    this.texts = new Map();
    this.drafts = new Map();                // what you're writing, by the note it answers ('new' for a note of your own)
    this.opened = new Set();                // the reply boxes you opened
    this.closed = new Set();                // the ones you closed on a question it asked you
    this.notices = new Map();               // why something couldn't be sent, by box
    this.sending = null;
    this.seen = new Set();                  // its notes you've read here, said once to the memory
    this.readTimers = new Map();
    this.reading = null;
    this.toMark = new Set();
    this.present = false;                   // someone has touched the page: moved, scrolled, typed
    this.hours = null;                      // the quiet hours as you're setting them, until saved
    this.shared = { query: '', author: '', shown: 50 };
    this.jevKey = '';                       // a key you're typing for Jev, held only here until it's sent
    this.bind();
  }

  /* ---------- counts and routes ---------- */

  count(tab) {
    const { life, mems } = this.ctx();
    return { shared: life.shared?.status === 'ready' ? life.shared.rows.length : null, log: null, memories: mems.length, beliefs: life.beliefs.length, questions: life.questions.open,
      journal: life.journal.length, notes: life.notes.length, hours: life.hours.length, settings: null }[tab];
  }
  /* its notes to you no one has read yet: the tab says so in the one colour that means "for you" */
  unread() { return this.ctx().life.notes.filter((n) => n.author === 'agent' && !n.read && !this.seen.has(n.id)).length;
  }
  hash() { return this.s.memory ? `#read/memory/${this.s.memory}` : `#read/${this.s.tab}`; }
  go({ tab = this.s.tab, memory = null } = {}, keepPage = false) {
    if (this.editing && this.editing.id !== memory) this.editing = null;
    const from = this.s.tab, changed = tab !== this.s.tab || memory !== this.s.memory;
    const inPlace = this.hooks.pane && tab === from;   // a memory opens beside the list, and the list stays as it is
    const apply = () => {
      this.s.tab = tab; this.s.memory = memory;
      if (!keepPage && !inPlace) this.s.shown = PAGE;
      this.render(changed && !inPlace, inPlace);
      this.hooks.open?.(memory);
      this.hooks.route?.(this.hash());
    };
    // a page may choreograph the change (the log's marker glides and its content trades places); otherwise, at once
    if (changed && !inPlace && this.hooks.transition) this.hooks.transition(apply, from, tab); else apply();
  }

  /* ---------- drawing ---------- */

  render(toTop = false, keepList = false) {
    this.tabsEl.innerHTML = this.tabs.map((k) => {
      const n = this.count(k);
      const fresh = k === 'notes' && this.unread() ? '<span class="unread" role="img" aria-label="new"></span>' : '';
      return `<button class="tab" role="tab" data-tab="${k}" aria-selected="${this.s.tab === k}">${fresh}${LABEL[k]}${n == null ? '' : `<small>${n.toLocaleString('en-US')}</small>`}</button>`;
    }).join('');
    const { byId } = this.ctx();
    const open = this.s.memory && byId.has(this.s.memory);
    const scroller = this.scroller();
    const top = scroller.scrollTop;
    // a live redraw never takes the search box away from someone typing in it
    const typing = document.activeElement?.id === 'room-search' ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
    const a = document.activeElement, typingIn = a?.dataset?.draft ? [a.dataset.draft, a.selectionStart, a.selectionEnd] : null;
    const list = () => ({ log: () => this.logHTML(), memories: () => this.memoriesHTML(), beliefs: () => this.beliefsHTML(), questions: () => this.questionsHTML(),
      journal: () => this.journalHTML(), notes: () => this.notesHTML(), hours: () => this.hoursHTML(), shared: () => this.sharedHTML(), settings: () => this.settingsHTML() }[this.s.tab]());
    // in the notebook a memory opens in the pane beside the list; in the mind's sheet, it takes the list's place
    const pane = this.hooks.pane;
    const fresh = pane && open && pane.showing !== this.s.memory;
    const stepping = fresh && pane.isOpen();       // walking the list isn't an occasion: the figure is simply there
    let wrote = !pane && open;
    if (!pane) this.bodyEl.innerHTML = open ? this.memoryHTML(this.s.memory) : list();
    else {
      if (!keepList) this.bodyEl.innerHTML = list();
      if (open) wrote = pane.show(this.s.memory, this.memoryHTML(this.s.memory)); else pane.hide();
      for (const row of this.bodyEl.querySelectorAll('[data-mem]')) {
        if (open && row.dataset.mem === this.s.memory) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
      }
    }
    if (this.s.tab === 'shared' && this.sending) {
      for (const control of this.bodyEl.querySelectorAll('button, input, textarea, select')) control.disabled = true;
    }
    this.restoreOpen();
    if (toTop) this.toTop(); else scroller.scrollTop = top;
    const search = this.find('#room-search');
    if (typing && search) { search.focus({ preventScroll: true }); search.setSelectionRange(...typing); }
    const draft = typingIn && this.find(`[data-draft="${CSS.escape(typingIn[0])}"]`);
    if (draft) { draft.focus({ preventScroll: true }); draft.setSelectionRange(typingIn[1], typingIn[2]); }
    // a key being typed is set back as a value, never written into the page
    const key = this.jevKey && this.find('[data-jev-key]');
    if (key) { key.value = this.jevKey; const save = this.find('[data-jev-save]'); if (save && this.sending !== 'jev') save.disabled = false; }
    this.watchReading();
    const plate = wrote && (pane ? pane.content : this.bodyEl).querySelector('.specimen canvas');
    if (plate) mountLife(plate, herbariumOf(this.ctx().mems), byId.get(this.s.memory), { open: (id) => this.go({ memory: id }), again: fresh, instant: stepping });
    const more = this.bodyEl.querySelector('.more-rows');
    if (more) new IntersectionObserver(([e], o) => { if (e.isIntersecting) { o.disconnect(); this.s.shown += 80; this.render(); } }, { root: this.viewRoot(), rootMargin: '400px' }).observe(more);
  }
  /* what's on the page, in the list or the pane */
  find(selector) { return this.hooks.pane?.content.querySelector(selector) || this.bodyEl.querySelector(selector); }
  scroller() { return this.sticky ? this.bodyEl : (this.hooks.scroller?.() || document.scrollingElement); }
  viewRoot() { const s = this.scroller(); return s === document.scrollingElement ? null : s; }
  toTop() {
    if (this.sticky) { this.bodyEl.scrollTop = 0; return; }
    const y = this.hooks.top ? this.hooks.top() : this.tabsEl.getBoundingClientRect().top + scrollY - 8;
    const s = this.scroller();
    if (s.scrollTop > y) s.scrollTop = y;
  }
  /* a live redraw waits while you're writing, so nothing you type is lost or jumps */
  refresh() {
    if ((this.bodyEl.contains(document.activeElement) || this.hooks.pane?.el.contains(document.activeElement)) && document.activeElement.matches('[data-draft], [data-jev-key]')) return;
    this.render();
  }

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

  /* Shared words stay in their own list, never in the mind's memory view. */
  sharedHTML() {
    const data = this.ctx().life.shared || { status: 'error', rows: [] }, busy = !!this.sending;
    if (data.status === 'off') return `<p class="empty">${SHARED.off}</p>`;
    if (data.status === 'error') return `<p class="empty" role="status">${SHARED.error}</p>`;
    const draft = this.drafts.get('shared-new') || '', notice = this.notices.get('shared-new');
    const authors = new Map(data.rows.map(m => [m.author, m.person ? SHARED.you : m.author]));
    const rows = data.rows.filter(m => (!this.shared.author || m.author === this.shared.author) && m.content.toLowerCase().includes(this.shared.query.toLowerCase()));
    return `<section class="shared-list" aria-label="${SHARED.title}" aria-busy="${busy}">
      <div class="compose new"><textarea class="field" rows="3" data-draft="shared-new" aria-label="${SHARED.placeholder}" placeholder="${SHARED.placeholder}"${busy ? ' disabled' : ''}>${esc(draft)}</textarea>
        <div class="acts"><span class="hint${notice ? ' flag' : ''}" role="status">${esc(notice || SHARED.hint)}</span>
        <button type="button" class="send" data-shared-add="1"${busy || !draft.trim() ? ' disabled' : ''}>${this.sending === 'shared-new' ? SHARED.adding : SHARED.add}</button></div></div>
      ${data.rows.length ? `<div class="tools"><div class="tools-top"><label class="searchw"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5L14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg><input id="room-search" class="search" type="search" value="${esc(this.shared.query)}" placeholder="${SHARED.search}" aria-label="${SHARED.search}"></label>
      <label class="sortw"><span class="vh">${SHARED.author}</span><select class="sort" data-shared-author="1"><option value="">${SHARED.all}</option>${[...authors].map(([id, name]) => `<option value="${esc(id)}"${this.shared.author === id ? ' selected' : ''}>${esc(name)}</option>`).join('')}</select></label></div></div>` : ''}
      <ul class="rows">${rows.slice(0, this.shared.shown).map(m => `<li class="jentry"><div class="meta"><span class="k">${esc(m.person ? SHARED.you : m.author)}</span>${m.model ? `<span>${esc(modelName(m.model))}</span>` : ''}<time datetime="${esc(m.born)}">${shortDay(at(m.born))}</time></div>${this.own(m.id, m.content)}${this.memActs(m, true)}</li>`).join('')}</ul>
      ${!rows.length ? `<p class="empty">${data.rows.length ? SHARED.none : SHARED.empty}</p>` : ''}
      ${rows.length > this.shared.shown ? `<button type="button" class="reply-open" data-shared-more="1"${busy ? ' disabled' : ''}>${SHARED.more}</button>` : ''}</section>`;
  }
  async sharedAdd() {
    if (this.sending || !this.hooks.send) return;
    const text = (this.drafts.get('shared-new') || '').trim();
    if (!text) return;
    this.sending = 'shared-new'; this.notices.delete('shared-new'); this.render();
    let answer;
    try { answer = await this.hooks.send({ command: 'shared', action: 'add', text }); }
    catch { answer = { error: SHARED.failed }; }
    this.sending = null;
    if (answer?.result) this.drafts.delete('shared-new');
    else this.notices.set('shared-new', answer?.error || SHARED.failed);
    this.render(); this.find('[data-draft="shared-new"]')?.focus();
  }

  /* ---------- memories ---------- */

  list() {
    const { mems } = this.ctx(), heat = this.ctx().heat;
    const q = this.s.query.trim().toLowerCase(), f = this.s.filter, s = this.s.sort;
    let out = mems.filter((m) => f === 'all' || (f === 'lessons' ? m.lesson : f === 'standing' ? m.standing : f === 'asked' ? m.asked
      : f === 'quiet' ? m.state === 'dormant' : f === 'warm' ? heat && heat(m.id) > 0.05 : f === 'colleagues' ? m.model && !sameModel(m.model, this.ctx().who.model)
      : f === 'new' ? this.isNew(m) : true));
    if (q) out = out.filter((m) => (m.content + ' ' + (m.impact || '')).toLowerCase().includes(q));
    const t = (m) => Date.parse(m.born);
    return out.sort((a, b) => s === 'recalled' ? b.recalls - a.recalls || t(b) - t(a) : s === 'connected' ? b.ties.length - a.ties.length
      : s === 'easiest' ? b.acc - a.acc : s === 'oldest' ? t(a) - t(b) : t(b) - t(a));
  }
  row(m) {
    return `<li><button class="rowb" data-mem="${esc(m.id)}"><div class="meta">${this.rowMeta(m)}</div>
      <div class="words">${esc(m.content)}</div></button></li>`;
  }
  rowMeta(m) {
    const heat = this.ctx().heat, { who } = this.ctx();
    const tags = [m.lesson ? 'a lesson' : null, m.standing ? 'standing' : null, m.asked ? 'asked about' : null, m.state === 'dormant' ? 'gone quiet' : null,
      m.model && !sameModel(m.model, who.model) ? modelName(m.model) : null].filter(Boolean);
    return `${this.isNew(m) ? '<span class="k new"><span class="unread" aria-hidden="true"></span>new</span>' : ''}<span>${shortDay(at(m.born))}</span>${tags.map((x) => `<span class="k2">${esc(x)}</span>`).join('')}${heat && heat(m.id) > 0.05 ? '<span class="warm">warm from its hours</span>' : ''}${m.recalls ? `<span>recalled ${m.recalls}×</span>` : ''}`;
  }
  /* formed since the person was last here */
  isNew(m) { const since = this.ctx().since; return !!since && Date.parse(m.born) > since; }
  memoriesHTML() {
    const { mems } = this.ctx(), all = this.list(), heat = this.ctx().heat;
    const fresh = mems.filter((m) => this.isNew(m)).length;
    const chip = (g, v, label) => `<button class="chip" data-${g}="${v}" aria-pressed="${this.s[g] === v}">${label}</button>`;
    const colleagues = mems.some((m) => m.model && !sameModel(m.model, this.ctx().who.model));
    const orders = [['newest', 'Newest'], ['oldest', 'Oldest'], ['recalled', 'Most recalled'], ['connected', 'Most connected'], ['easiest', 'Easiest to reach']];
    return `<div class="tools${this.sticky ? ' stick' : ''}"><div class="tools-top">
        <label class="searchw"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5L14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg><input class="search" id="room-search" type="search" placeholder="Search its memory" value="${esc(this.s.query)}" aria-label="Search its memory"></label>
        <label class="sortw"><span class="vh">Order</span><select class="sort" data-sort-select="1">${orders.map(([v, l]) => `<option value="${v}"${this.s.sort === v ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      </div>
      <div class="chips">${chip('filter', 'all', 'All')}${fresh ? chip('filter', 'new', `New <span class="n">${fresh}</span>`) : ''}${heat ? chip('filter', 'warm', 'Warm') : ''}${chip('filter', 'lessons', 'Lessons')}${chip('filter', 'standing', 'Standing')}${chip('filter', 'asked', 'Asked about')}${chip('filter', 'quiet', 'Gone quiet')}${colleagues ? chip('filter', 'colleagues', 'By colleagues') : ''}
        <span class="count">${all.length === mems.length ? plural(mems.length, 'memory', 'memories') : `${all.length.toLocaleString('en-US')} of ${mems.length.toLocaleString('en-US')}`}</span></div></div>
      <ul class="rows">${all.slice(0, this.s.shown).map((m) => this.row(m)).join('')}</ul>${all.length > this.s.shown ? '<div class="more-rows"></div>' : ''}
      ${mems.length ? (all.length ? '' : '<p class="empty">Nothing in its memory matches that.</p>') : '<p class="empty">Its memory is empty.</p>'}`;
  }
  memoryHTML(id) {
    const { who, life, mems, byId } = this.ctx(), m = mems[byId.get(id)];
    const d = at(m.born);
    const asks = life.questions.asked.filter((q) => q.about === id), answers = life.questions.answered.filter((q) => q.about === id);
    const beliefs = life.beliefs.filter((b) => (b.supports || []).includes(id));
    const hours = life.hours.filter((h) => { const t = h.trail || {}; return [...(t.woke || []), ...(t.waiting || []), ...(t.reached || [])].includes(id); });
    const sign = [`${longDay(d)}, ${clock(d)}`, signedBy(m, who), m.standing ? 'standing: how it works every session' : null].filter(Boolean).join(' · ');
    const link = this.hooks.mindLink?.(id);
    const H = herbariumOf(mems), hi = byId.get(id), hc = H.cells[hi], n2 = (v) => (v ?? 0).toFixed(2);
    const readings = [['strength', n2(hc.strength)], ['stability', n2(hc.stability)], ['reach', n2(hc.accessibility)], ['links', hc.links], ['recalled', `${hc.accessCount}×`]];
    const paned = !!this.hooks.pane;
    const also = (key, label, count, html) => `<details class="also" data-key="${esc(`${id}:${key}`)}"><summary><span>${label}</span>${count ? `<span class="n">${count}</span>` : ''}</summary>${html}</details>`;
    return `<div class="detail">${paned ? `<div class="pane-h"><div class="meta">${this.rowMeta(m)}</div><div class="pane-acts">
        <button class="icon-b" type="button" data-step="-1" aria-label="Previous memory" title="Previous (↑)"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4 10l4-4 4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
        <button class="icon-b" type="button" data-step="1" aria-label="Next memory" title="Next (↓)"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
        <button class="icon-b" type="button" data-back="1" aria-label="Close" title="Close (Esc)"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div></div>` : `<button class="back" data-back="1">← ${LABEL[this.s.tab] === 'Memories' ? 'All memories' : `Back to ${LABEL[this.s.tab].toLowerCase()}`}</button>`}
      <figure class="specimen"><canvas role="img" aria-label="${esc(lifeWords(H, hi, lifeOf(H, hi)))}, drawn as a specimen"></canvas></figure>
      <div class="words">${esc(m.content)}</div>
      ${m.impact ? `<div class="changed"><span class="label">What it changed, in its words</span><p>${esc(m.impact)}</p></div>` : ''}
      <div class="about">
        <span class="life">${esc(lifeWords(H, hi, lifeOf(H, hi)))}</span>
        <span class="readings">${readings.map(([k, v]) => `<span><i>${k}</i>${v}</span>`).join('')}</span>
        <span class="signed">${esc(sign)}${m.state === 'dormant' ? ' · gone quiet' : ''}</span>
      </div>
      ${this.memActs(m)}
      <div class="alsos">
        ${link ? `<a class="also-link" href="${esc(link)}"><span>See it in the mind</span></a>` : ''}
        ${m.ties.length ? also('ties', 'Tied to', m.ties.length.toLocaleString('en-US'), `<ul class="rows">${m.ties.slice(0, 24).map(([tid, rel]) => { const t = mems[byId.get(tid)]; if (!t) return '';
          return `<li><button class="rowb" data-mem="${esc(tid)}"><div class="meta"><span>${shortDay(at(t.born))}</span><span class="k">${RELATION[rel] || esc(rel)}</span></div><div class="words">${esc(t.content)}</div></button></li>`; }).join('')}</ul>${m.ties.length > 24 ? `<p class="count">and ${m.ties.length - 24} more</p>` : ''}`) : ''}
        ${beliefs.length ? also('beliefs', 'Beliefs resting on it', beliefs.length, `<ul class="lines">${beliefs.map((b) => `<li><span class="a">${esc(b.text)}</span><span class="m">held at ${Math.round(b.confidence * 100)}%</span></li>`).join('')}</ul>`) : ''}
        ${hours.length ? also('hours', 'In its hours', hours.length, `<ul class="lines">${hours.map((h) => { const t = h.trail || {};
          const how = (t.reached || []).includes(id) ? 'reached for it' : (t.waiting || []).includes(id) ? 'found it waiting, as a question' : 'woke with it in hand';
          return `<li>${KIND[h.kind] || esc(h.kind)}, ${shortDay(at(h.start))} at ${clock(at(h.start))}: ${how}${h.practice ? ' (practice)' : ''}</li>`; }).join('')}</ul>`) : ''}
        ${asks.length ? also('asks', 'What its memory asks about it', asks.length, `<ul class="lines">${asks.map((q) => `<li>${esc(question(q.prompt))}<span class="m">${putTo(q.shown)}</span></li>`).join('')}</ul>`) : ''}
        ${answers.length ? also('answers', 'Its answers', answers.length, `<ul class="lines">${answers.map((q) => `<li>${esc(question(q.prompt))}<span class="a">${esc(q.answer)}</span></li>`).join('')}</ul>`) : ''}
        <details class="also key" data-key="${esc(`${id}:key`)}"><summary><span>How to read the figure</span></summary><ul>
          <li>Its size is how strongly it's kept. Round, it's a lesson; a drop is an experience, its front toward what it became.</li>
          <li>A spine for each link, as long as the link is strong${hc.links > 64 ? ` (its strongest 64 of ${hc.links})` : ''}. Barred, it supports; barbed, it contradicts. The stalk joins an experience to its lesson.</li>
          <li>A ring for each doubling of the times it came back. The centre grows as it settles. The threads around it reach as far as it's easy to reach.</li>
          <li>Drawn dashed and hollow, it has gone quiet.</li></ul></details>
      </div>
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
    const { life, byId, mems } = this.ctx(), Q = life.questions;
    if (!Q.open && !Q.answered.length) return '<p class="empty">Its memory isn’t asking it anything right now.</p>';
    const kinds = Object.entries(Q.byKind || {}).sort((a, b) => (ASK_ORDER[a[0]] ?? 9) - (ASK_ORDER[b[0]] ?? 9));
    // the questions grounded in meaning first; the ones counted from recurring words after them
    const list = Q.asked.filter((q) => this.s.qkind === 'all' || q.kind === this.s.qkind)
      .sort((a, b) => (ASK_ORDER[a.kind] ?? 9) - (ASK_ORDER[b.kind] ?? 9) || Date.parse(b.at) - Date.parse(a.at));
    const rows = list.slice(0, this.s.shown).map((q) => `<li><button class="rowb" ${byId.has(q.about) ? `data-mem="${esc(q.about)}"` : 'disabled'}>
      <div class="meta"><span class="k">${(ASK[q.kind] || [q.kind])[0]}</span><span>${shortDay(at(q.at))}</span><span>${putTo(q.shown)}</span></div>
      <div class="words">${esc(byId.has(q.about) ? mems[byId.get(q.about)].content : q.excerpt || question(q.prompt))}</div></button></li>`).join('');
    const answered = Q.answered.map((a) => `<li><button class="rowb" ${byId.has(a.about) ? `data-mem="${esc(a.about)}"` : 'disabled'}>
      <div class="meta"><span class="k">${(ASK[a.kind] || [a.kind])[0]}</span><span>answered ${shortDay(at(a.at))}</span></div>
      <div class="q">${esc(question(a.prompt))}</div><div class="ans">${esc(a.answer)}</div></button></li>`).join('');
    return `<div class="kinds" role="group" aria-label="Kinds of question">${kinds.map(([k, n]) => `<button class="kindb" data-qkind="${k}" aria-pressed="${this.s.qkind === k}"><b>${n}</b><span>${(ASK[k] || [k])[0]}</span></button>`).join('')}</div>
      <p class="note-k">${this.s.qkind !== 'all' && ASK[this.s.qkind] ? esc(ASK[this.s.qkind][1]) + ' ' : ''}${this.s.qkind !== 'all' ? ' <button class="chip" data-qkind="all">Show every kind</button>' : ''}</p>
      <ul class="rows" style="margin-top:var(--s3)">${rows}</ul>${list.length > this.s.shown ? '<div class="more-rows"></div>' : ''}
      ${answered ? `<span class="label sub-h">Answered, in its words</span><ul class="rows" style="margin-top:var(--s2)">${answered}</ul>` : ''}`;
  }
  journalHTML() {
    const { life } = this.ctx();
    if (!life.journal.length) return '<p class="empty">Its journal is empty. It writes there only when something’s there.</p>';
    return life.journal.map((e) => `<div class="jentry"><div class="meta"><span>${longDay(at(e.at))}, ${clock(at(e.at))}</span><span>${e.written === 'between_sessions' ? 'written between conversations' : 'written in conversation'}</span>${e.mood ? `<span>mood, in its words: ${esc(e.mood)}</span>` : ''}</div>
      ${this.entry(e.id, e.text)}</div>`).join('');
  }
  /* ---------- notes: what it has to say to you, and what you say back ---------- */

  /* its notes and yours, gathered into conversations: each note with the replies under it, oldest first; the
     conversation with the newest word comes first */
  threads() {
    const { life } = this.ctx();
    const byId = new Map(life.notes.map((n) => [n.id, n]));
    const root = (n) => { let x = n; for (let i = 0; i < 50 && x.replyTo && byId.has(x.replyTo); i++) x = byId.get(x.replyTo); return x; };
    const groups = new Map();
    for (const n of life.notes) { const r = root(n).id; if (!groups.has(r)) groups.set(r, []); groups.get(r).push(n); }
    const time = (n) => Date.parse(n.at);
    return [...groups.values()].map((list) => list.sort((a, b) => time(a) - time(b)))
      .sort((a, b) => time(b[b.length - 1]) - time(a[a.length - 1]));
  }
  /* the question it left you, if its last word in a conversation asks one and you haven't answered yet */
  asks(list) {
    const last = list[list.length - 1];
    return last.author === 'agent' && /\?\s*$/.test(last.text.trim()) ? last : null;
  }
  notesHTML() {
    const { who } = this.ctx(), threads = this.threads();
    // a mind whose memory is from before notes (an older store, found beside this one) is only read here
    const composer = who.unfiled ? `<p class="set-d">${esc(who.name)}’s memory is from before notes, so this page only reads it.</p>`
      : this.box('new', `Leave ${who.name} a note`, 'It wakes with it, once, in its next session.');
    if (!threads.length) return composer + `<p class="empty">No notes yet. It leaves one only when it passes the room test: something it would say if ${esc(person(who) === 'you' ? 'you' : person(who))} walked in right now.</p>`;
    const open = threads.filter((t) => this.asks(t)), rest = threads.filter((t) => !this.asks(t));
    return composer
      + (open.length ? `<h3 class="asked-h first label"><span class="unread" aria-hidden="true"></span>Waiting on ${person(who) === 'you' ? 'you' : esc(person(who))}<span class="n">${open.length}</span></h3>${open.map((t) => this.threadHTML(t)).join('')}` : '')
      + (open.length && rest.length ? `<h3 class="asked-h label">Earlier<span class="n">${rest.length}</span></h3>` : '')
      + rest.map((t) => this.threadHTML(t)).join('');
  }
  threadHTML(list) {
    const { who } = this.ctx();
    const by = (n) => (n.author === 'agent' ? esc(who.name) : who.person ? esc(who.person) : 'You');
    const dot = (n) => n.author === 'agent' && !n.read && !this.seen.has(n.id);
    const head = (n) => `<div class="meta">${dot(n) ? '<span class="unread" role="img" aria-label="new"></span>' : ''}<span class="k">${by(n)}</span>`
      + `<span>${longDay(at(n.at))}, ${clock(at(n.at))}</span>${n.kind === 'pickup' ? '<span>after our hour</span>' : ''}`
      + `${n.author === 'person' ? `<span>${n.delivered ? 'it has woken with this' : 'it hasn’t woken since'}</span>` : ''}</div>`;
    const watched = (n) => (n.author === 'agent' && !n.read && !this.seen.has(n.id) ? ` data-unread="${esc(n.id)}"` : '');
    const turn = (n, i) => `<div class="turn${i ? ' later' : ''}${n.author === 'person' ? ' yours' : ''}"${watched(n)}>${head(n)}${this.own(n.id, n.text, 'text note', 600)}</div>`;
    const answer = [...list].reverse().find((n) => n.author === 'agent');   // a reply answers its newest word here
    const asked = this.asks(list);
    // a question it asked you comes with its answer box already open
    if (asked && !this.closed.has(asked.id)) this.opened.add(asked.id);
    return `<article class="jentry thread">${list.map(turn).join('')}${answer && !who.unfiled ? this.box(answer.id, asked ? 'Answer' : 'Reply', '') : ''}</article>`;
  }

  /* a place to write: closed, one quiet word; open, a field and Send. What you type stays while the page refreshes
     itself and while you look elsewhere. */
  box(key, label, hint) {
    const open = key === 'new' || this.opened.has(key), draft = this.drafts.get(key) || '', k = esc(key);
    if (!open) return `<button class="reply-open" type="button" data-reply="${k}">${esc(label)}</button>`;
    const notice = this.notices.get(key);
    const place = key === 'new' ? label : label === 'Answer' ? 'Your answer, in your own words' : 'Your reply, in your own words';
    return `<div class="compose${key === 'new' ? ' new' : ''}">
      <textarea class="field" rows="${key === 'new' ? 2 : 3}" data-draft="${k}" placeholder="${esc(place)}" aria-label="${esc(key === 'new' ? label : label === 'Answer' ? 'Your answer' : 'Your reply')}">${esc(draft)}</textarea>
      <div class="acts"><span class="hint${notice ? ' flag' : ''}" aria-live="polite">${esc(notice || hint)}</span>${key === 'new' ? '' : `<button class="cancel" type="button" data-cancel="${k}">Cancel</button>`}<button class="send" type="button" data-send="${k}"${draft.trim() && this.sending !== key ? '' : ' disabled'}>${this.sending === key ? 'Sending…' : 'Send'}</button></div></div>`;
  }
  async send(key) {
    const text = (this.drafts.get(key) || '').trim();
    if (!text || this.sending || !this.hooks.send) return;
    this.sending = key; this.notices.delete(key); this.render();
    let answer;
    try { answer = await this.hooks.send(key === 'new' ? { command: 'note', text } : { command: 'reply', note_id: key, text }); }
    catch { answer = { error: 'It couldn’t be sent just now. Is `mnemos log` still running?' }; }
    this.sending = null;
    if (answer?.result) { this.drafts.delete(key); this.opened.delete(key); }
    else this.notices.set(key, answer?.error || 'It couldn’t be sent.');
    this.render();
  }

  /* A note of its own counts as read once most of it (or most of your screen) has shown it for a moment, on a page in
     front of someone who has touched it. Nothing short of that counts: a page open in a tab no one looks at, or one an
     agent reads for itself, marks nothing, since a note marked read unseen is a note lost. Each is said once. */
  watchReading() {
    this.reading?.disconnect();
    for (const t of this.readTimers.values()) clearTimeout(t);
    this.readTimers.clear();
    if (!this.hooks.read || !this.present || document.visibilityState !== 'visible') return;
    const notes = this.bodyEl.querySelectorAll('[data-unread]');
    if (!notes.length) return;
    const root = this.viewRoot();
    this.reading = new IntersectionObserver((entries) => {
      const view = root ? root.clientHeight : innerHeight;
      for (const e of entries) {
        const id = e.target.dataset.unread;
        const showing = e.isIntersecting && e.intersectionRect.height >= Math.min(e.boundingClientRect.height, view) * 0.6;
        if (showing && !this.readTimers.has(id)) this.readTimers.set(id, setTimeout(() => this.markSeen(id), SEEN_AFTER));
        if (!showing && this.readTimers.has(id)) { clearTimeout(this.readTimers.get(id)); this.readTimers.delete(id); }
      }
    }, { root, threshold: [0, 0.2, 0.4, 0.6, 0.8, 1] });
    notes.forEach((n) => this.reading.observe(n));
  }
  markSeen(id) {
    this.readTimers.delete(id);
    if (!this.present || document.visibilityState !== 'visible' || this.seen.has(id)) return;
    this.seen.add(id); this.toMark.add(id);
    clearTimeout(this.marking);
    this.marking = setTimeout(() => {
      const ids = [...this.toMark]; this.toMark.clear();
      // not said? then it's still unread, and the next look tries again
      this.hooks.read(ids).catch(() => ids.forEach((i) => this.seen.delete(i)));
    }, 300);
  }
  hoursHTML() {
    const { life } = this.ctx();
    if (!life.hours.length) return '<p class="empty">No quiet hour has run yet. When hours are turned on, each one appears here as soon as it ends.</p>';
    return `<ul class="rows">${life.hours.map((h) => { const s = at(h.start), k = temperature(h);
      return `<li><button class="rowb" data-hour="${esc(h.id)}"><div class="meta"><span>${shortDay(s)}, ${clock(s)}</span><span class="k">${KIND[h.kind] || esc(h.kind)}</span>${h.practice ? '<span>practice</span>' : ''}<span class="${k > 0.06 ? 'warm' : ''}">${tempWord(k, h).toLowerCase()}</span></div>
        <div class="q">${esc(trailSentence(h))}</div>${h.journal.length ? `<div class="ex">${esc(firstLine(h.journal[h.journal.length - 1].text, 200))}</div>` : ''}</button></li>`; }).join('')}</ul>`;
  }

  /* ---------- a memory, corrected in the person's words, or let go ----------
   * The two things a person can do to a memory itself, each said plainly before it's done. A correction replaces its
   * words with the person's (its own stay in its history) and it wakes knowing, once; letting one go archives it, never
   * deletes it, and it's told once that a memory was let go, never what it said. Neither is offered for a mind the page
   * only reads. */
  memActs(m, shared = false) {
    const { who } = this.ctx();
    if ((!shared && who.unfiled) || !this.hooks.send) return '';
    const key = `fix:${m.id}`, mode = this.editing?.id === m.id ? this.editing.mode : null, notice = this.notices.get(key);
    if (mode === 'correct') {
      const draft = this.drafts.has(key) ? this.drafts.get(key) : m.content;
      return `<div class="compose fix"><span class="label">Correct it, in your words</span>
        <textarea class="field" rows="5" data-draft="${esc(key)}" aria-label="The memory, corrected in your words">${esc(draft)}</textarea>
        <div class="acts"><span class="hint${notice ? ' flag' : ''}" aria-live="polite">${esc(notice || (shared ? SHARED.correction : `Its own words stay in its history. ${who.name} wakes knowing you corrected it, once.`))}</span>
          <button class="cancel" type="button" data-mem-cancel="1">Cancel</button>
          <button class="send" type="button" data-fix-save="${esc(m.id)}"${draft.trim() && draft.trim() !== m.content.trim() && this.sending !== key ? '' : ' disabled'}>${this.sending === key ? 'Saving…' : 'Save correction'}</button></div></div>`;
    }
    if (mode === 'forget') {
      return `<div class="confirm" role="alertdialog" aria-labelledby="let-go-h"><div class="set-title" id="let-go-h">Let this memory go?</div>
        <p class="set-d">${shared ? SHARED.withdraw : `It won't come back by its words, its meaning or its id. It's kept in the archive, not deleted, and ${esc(who.name)} will know, once, that you let a memory go, though not what it said.`}</p>
        <div class="acts"><span class="hint${notice ? ' flag' : ''}" aria-live="polite">${esc(notice || '')}</span>
          <button class="cancel" type="button" data-mem-cancel="1">Keep it</button>
          <button class="send danger" type="button" data-forget-yes="${esc(m.id)}"${this.sending === key ? ' disabled' : ''}>${this.sending === key ? 'Letting go…' : 'Let it go'}</button></div></div>`;
    }
    return `<div class="mem-acts">${!shared || m.editable ? `<button class="reply-open" type="button" data-mem-act="correct" data-id="${esc(m.id)}">Correct it</button>` : ''}
      <button class="reply-open" type="button" data-mem-act="forget" data-id="${esc(m.id)}">Let it go</button></div>`;
  }
  async memChange(id, request) {
    if (this.s.tab === 'shared') request = { ...request, command: 'shared', action: request.command };
    const key = `fix:${id}`;
    if (this.sending) return;
    this.sending = key; this.notices.delete(key); this.render();
    let answer;
    try { answer = await this.hooks.send(request); }
    catch { answer = { error: 'It couldn’t be changed just now. Is `mnemos log` still running?' }; }
    this.sending = null;
    if (answer?.result) {
      this.editing = null; this.drafts.delete(key);
      const next = request.command === 'correct' ? answer.result.id || answer.result.memory?.id : null;
      const { byId } = this.ctx();
      return this.go({ tab: this.s.tab, memory: next && byId.has(next) ? next : null });
    }
    this.notices.set(key, answer?.error || 'It couldn’t be changed.');
    this.render();
  }

  /* ---------- settings: what's the person's to decide ---------- */

  /* The quiet hours are the one setting that's yours: whether it has them, and when each starts. Everything else in
     Mnemos tunes itself. What's set here is what `mnemos daemon install --hours` would do, on this machine. */
  settingsHTML() {
    const { who, life } = this.ctx();
    const plan = life.schedule || [], at = (k) => plan.find((p) => p.kind === k);
    const hhmm = (w) => (w ? `${String(w.Hour ?? 0).padStart(2, '0')}:${String(w.Minute ?? 0).padStart(2, '0')}` : '');
    const DEFAULT = { mine: '08:00', ours: '19:00', dream: '03:30' };
    const saved = { ...{ runner: 'claude-code', model: '' }, ...life.hourSettings, on: plan.length > 0, mine: hhmm(at('mine')?.when) || DEFAULT.mine, ours: hhmm(at('ours')?.when) || DEFAULT.ours, dream: hhmm(at('dream')?.when) || DEFAULT.dream };
    const h = this.hours || saved, changed = JSON.stringify(h) !== JSON.stringify(saved);
    const notice = this.notices.get('hours');
    const off = plan.filter((p) => !p.loaded);
    const codex = h.runner === 'codex';
    const row = (k, label, what) => `<label class="set-row"><span><span class="set-k">${label}</span><span class="set-d">${what}</span></span>
      <input class="set-time" type="time" data-hours-time="${k}" value="${esc(h[k])}"${h.on && (!codex || k === 'dream') ? '' : ' disabled'} aria-label="${label}, starts at"></label>`;
    const hoursPanel = who.unfiled ? `<div class="belief set"><div class="set-title">Quiet hours</div>
        <p class="set-d">${esc(who.name)}’s memory is from before quiet hours, so there’s nothing here to set. This page only reads it.</p></div>` : null;
    return `<section class="settings">
      ${hoursPanel || `<div class="belief set">
        <div class="set-head"><div><div class="set-title">Quiet hours</div>
          <p class="set-d">Time between conversations that’s ${esc(who.name)}’s own: an hour a day to itself, half an hour for the day’s work, and a short time each night to dream over its memory. They use the selected runner and its signed-in account. Codex currently runs only the dream.</p></div>
          <button class="switch" type="button" role="switch" aria-checked="${h.on}" data-hours-on="${h.on ? 'off' : 'on'}"><span class="knob" aria-hidden="true"></span><span class="vh">Quiet hours</span></button></div>
        <div class="set-rows">
          <label class="set-row"><span class="set-k">Runner</span><select class="set-choice" data-hours-runner aria-label="Quiet-hour runner"><option value="claude-code"${!codex ? ' selected' : ''}>Claude Code</option><option value="codex"${codex ? ' selected' : ''}>Codex</option></select></label>
          <label class="set-row"><span class="set-k">Model</span><input class="set-model" type="text" data-hours-model value="${esc(h.model || '')}" placeholder="Automatic" aria-label="Quiet-hour model"></label>
          ${row('mine', 'Its own hour', codex ? 'Available with Claude Code' : 'An hour to itself')}${row('ours', 'Our hour', codex ? 'Available with Claude Code' : 'Half an hour for the day’s work')}${row('dream', 'The dream', 'A short time each night')}</div>
        ${off.length ? `<p class="set-d flag">${off.length === plan.length ? 'Scheduled, but not loaded: they won’t run until they are.' : `${plural(off.length, 'hour')} scheduled but not loaded.`}</p>` : ''}
        <div class="acts"><span class="hint${notice ? ' flag' : ''}" aria-live="polite">${esc(notice || (changed ? 'Not saved yet.' : h.on ? 'Scheduled on this machine.' : 'Off. Nothing runs between conversations.'))}</span>
          ${changed ? '<button class="cancel" type="button" data-hours-reset="1">Undo</button>' : ''}
          <button class="send" type="button" data-hours-save="1"${changed && this.sending !== 'hours' ? '' : ' disabled'}>${this.sending === 'hours' ? 'Saving…' : 'Save'}</button></div>
      </div>`}
      ${this.jevPanel()}
      ${this.tellPanel()}
      <div class="belief set">
        <div class="set-title">Where it lives</div>
        <dl class="set-facts">
          <dt>Its memory</dt><dd>${esc(who.store || '')}${life.memory?.storeBytes ? ` · ${(life.memory.storeBytes / 1e6).toFixed(0)} MB` : ''}</dd>
          <dt>Memories</dt><dd>${(life.memory?.count || 0).toLocaleString('en-US')} it can reach${life.memory?.states?.archived ? `, ${life.memory.states.archived.toLocaleString('en-US')} let go` : ''}</dd>
          <dt>Agent</dt><dd>${esc(who.agentId || '')}${who.model ? ` · signs as ${esc(who.name)}` : ''}</dd>
          <dt>You</dt><dd>${who.person ? esc(who.person) : 'not named: start the page with --person-name, or set MNEMOS_PERSON_NAME'}</dd>
        </dl>
        <p class="set-d set-foot">On this machine only. Nothing here leaves it${life.jev?.on && life.jev?.key ? ', except what Jev is sent, above' : ''}.</p>
      </div>
    </section>`;
  }
  /* Jev, TypeSafe's judge of which memories bear on each message you send: on only with your own key, and off until
     you turn it on. What leaves the machine is said beside the switch. The key is never shown back, only that one is
     saved; it's sent once, to `mnemos log`, and kept nowhere on the page. */
  jevPanel() {
    const j = this.ctx().life.jev || {}, on = !!(j.on && j.key), busy = this.sending === 'jev';
    const notice = this.notices.get('jev'), n = (x) => Number(x || 0).toLocaleString('en-US');
    const hint = notice || (j.env ? 'Where this page runs, MNEMOS_CUE_JUDGE decides, so this switch can’t change it.'
      : on ? 'On. Jev judges each message you send.' : j.key ? 'Off. A key is saved; nothing leaves this machine.' : 'Off. Nothing leaves this machine.');
    return `<div class="belief set">
      <div class="set-head"><div><div class="set-title">Jev</div>
        <p class="set-d">With each message you send, a few memories might come up. Jev judges which of them really bear on it, so the ones that come up are the ones that matter. It’s a service from TypeSafe, and it runs only with a key of your own.</p></div>
        <button class="switch" type="button" role="switch" aria-checked="${on}" data-jev-on="${on ? 'off' : 'on'}"${j.key && !j.env && !busy ? '' : ' disabled'}><span class="knob" aria-hidden="true"></span><span class="vh">Jev</span></button></div>
      <div class="set-leaves"><span class="set-k">What leaves this machine</span>
        <p class="set-d">While Jev is on: each message you send, cut to ${n(j.messageChars)} characters, and the few memories that might come up with it (at most ${n(j.candidates)}, each cut to ${n(j.lineChars)} characters), sent to TypeSafe’s service at ${esc(j.host || 'api.typesafe.ai')}. No ids, no dates, nothing that says whose memory it is. Jev only decides what comes up: it never changes a memory, and nothing it answers is kept.</p></div>
      <div class="set-rows">${j.key
        ? `<div class="set-row"><span><span class="set-k">Key</span><span class="set-d">A key is saved on this machine.</span></span><button class="cancel" type="button" data-jev-remove="1"${busy ? ' disabled' : ''}>Remove key</button></div>`
        : `<label class="set-row"><span><span class="set-k">Key</span><span class="set-d">Your TypeSafe key. It’s kept on this machine, readable only by you.</span></span><input class="set-key" type="password" autocomplete="off" spellcheck="false" data-jev-key="1"${busy ? ' disabled' : ''} aria-label="Your TypeSafe key"></label>`}</div>
      <div class="acts"><span class="hint${notice ? ' flag' : ''}" aria-live="polite">${esc(hint)}</span>
        ${j.key ? '' : `<button class="send" type="button" data-jev-save="1" disabled>${busy ? 'Saving…' : 'Save key'}</button>`}</div>
    </div>`;
  }
  async jevSend(request) {
    if (this.sending || !this.hooks.send) return;
    this.sending = 'jev'; this.notices.delete('jev'); this.render();
    let answer;
    try { answer = await this.hooks.send({ command: 'jev', ...request }); }
    catch { answer = { error: 'It couldn’t be changed just now. Is `mnemos log` still running?' }; }
    this.sending = null;
    if (answer?.result) this.jevKey = ''; else this.notices.set('jev', answer?.error || 'It couldn’t be changed.');
    this.render();
  }
  /* a quiet notification when it asks you something, only if you want one */
  tellPanel() {
    const { who } = this.ctx();
    if (who.unfiled || !canTell()) return '';
    const on = telling(who.agentId), denied = refused();
    return `<div class="belief set"><div class="set-head"><div><div class="set-title">Tell me when it asks me something</div>
      <p class="set-d">${denied ? 'Your browser is set not to allow notifications from this page. Allow them for this address in the browser’s site settings, then turn this on.'
        : `One quiet notification when ${esc(who.name)} leaves you a question, only while this page isn’t in front of you. Each question is told once, however many of its pages are open.`}</p></div>
      <button class="switch" type="button" role="switch" aria-checked="${on}" data-tell="${on ? 'off' : 'on'}"${denied ? ' disabled' : ''}><span class="knob" aria-hidden="true"></span><span class="vh">Tell me when it asks me something</span></button></div></div>`;
  }
  currentHours() {
    if (this.hours) return this.hours;
    const plan = this.ctx().life.schedule || [], at = (k) => plan.find((p) => p.kind === k)?.when;
    const hhmm = (w, d) => (w ? `${String(w.Hour ?? 0).padStart(2, '0')}:${String(w.Minute ?? 0).padStart(2, '0')}` : d);
    return { runner: 'claude-code', model: '', ...this.ctx().life.hourSettings, on: plan.length > 0, mine: hhmm(at('mine'), '08:00'), ours: hhmm(at('ours'), '19:00'), dream: hhmm(at('dream'), '03:30') };
  }
  async saveHours() {
    const h = this.hours;
    if (!h || this.sending || !this.hooks.send) return;
    this.sending = 'hours'; this.notices.delete('hours'); this.render();
    let answer;
    try { answer = await this.hooks.send({ command: 'hours', on: h.on, runner: h.runner, model: h.model, mine: h.mine, ours: h.ours, dream: h.dream }); }
    catch { answer = { error: 'It couldn’t be changed just now. Is `mnemos log` still running?' }; }
    this.sending = null;
    if (answer?.result) this.hours = null; else this.notices.set('hours', answer?.error || 'It couldn’t be changed.');
    this.render();
  }

  /* ---------- events ---------- */

  bind() {
    this.tabsEl.addEventListener('click', (e) => { const t = e.target.closest('[data-tab]'); if (t) { this.s.qkind = 'all'; this.go({ tab: t.dataset.tab }); } });
    for (const body of [this.bodyEl, this.hooks.pane?.el].filter(Boolean)) this.listen(body);
    // someone is here: only then does a note on screen count as read
    const here = () => { if (!this.present) { this.present = true; this.watchReading(); } };
    for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart']) addEventListener(ev, here, { passive: true, once: true });
    document.addEventListener('visibilitychange', () => this.watchReading());
  }
  listen(body) {
    body.addEventListener('click', (e) => {
      if (e.target.closest('[data-shared-add]')) return this.sharedAdd();
      if (e.target.closest('[data-shared-more]')) { this.shared.shown += 50; this.render(); (this.find('[data-shared-more]') || this.find('[data-shared-add]'))?.focus(); return; }
      const fold = e.target.closest('[data-fold]');
      if (fold) {
        const id = fold.dataset.fold, open = !this.whole.has(id);
        if (open) this.whole.add(id); else this.whole.delete(id);
        const text = this.texts.get(id) || '';
        fold.previousElementSibling.textContent = open ? text : opening(text);
        fold.setAttribute('aria-expanded', open); fold.textContent = open ? 'Show less' : 'Read the whole entry';
        return;
      }
      const open = e.target.closest('[data-reply]');
      if (open) {
        this.opened.add(open.dataset.reply); this.closed.delete(open.dataset.reply); this.render();
        return this.find(`[data-draft="${CSS.escape(open.dataset.reply)}"]`)?.focus();
      }
      const cancel = e.target.closest('[data-cancel]');
      if (cancel) { const k = cancel.dataset.cancel; this.opened.delete(k); this.closed.add(k); this.drafts.delete(k); this.notices.delete(k); return this.render(); }
      const send = e.target.closest('[data-send]'); if (send) return this.send(send.dataset.send);
      const act = e.target.closest('[data-mem-act]');
      if (act) {
        this.editing = { id: act.dataset.id, mode: act.dataset.memAct }; this.render();
        return this.find(act.dataset.memAct === 'correct' ? '.fix .field' : '[data-mem-cancel]')?.focus();
      }
      if (e.target.closest('[data-mem-cancel]')) { const id = this.editing?.id; if (id) this.drafts.delete(`fix:${id}`); this.editing = null; this.render(); if (this.s.tab === 'shared' && id) this.find(`[data-mem-act][data-id="${CSS.escape(id)}"]`)?.focus(); return; }
      const fix = e.target.closest('[data-fix-save]');
      if (fix) { const id = fix.dataset.fixSave; return this.memChange(id, { command: 'correct', memory_id: id, text: (this.drafts.get(`fix:${id}`) || '').trim() }); }
      const yes = e.target.closest('[data-forget-yes]');
      if (yes) { const id = yes.dataset.forgetYes; return this.memChange(id, { command: 'forget', memory_id: id, confirmed: true }); }
      const tellSw = e.target.closest('[data-tell]');
      if (tellSw) { const { who, life } = this.ctx(); return setTelling(who.agentId, tellSw.dataset.tell === 'on', life.notes).then(() => this.render()); }
      const sw = e.target.closest('[data-hours-on]');
      if (sw) { this.hours = { ...this.currentHours(), on: sw.dataset.hoursOn === 'on' }; this.notices.delete('hours'); return this.render(); }
      if (e.target.closest('[data-hours-reset]')) { this.hours = null; this.notices.delete('hours'); return this.render(); }
      if (e.target.closest('[data-hours-save]')) return this.saveHours();
      const jevSw = e.target.closest('[data-jev-on]');
      if (jevSw) return this.jevSend({ on: jevSw.dataset.jevOn === 'on' });
      if (e.target.closest('[data-jev-remove]')) return this.jevSend({ remove_key: true });
      if (e.target.closest('[data-jev-save]')) { const key = this.jevKey.trim(); return key ? this.jevSend({ key }) : undefined; }
      const pic = e.target.closest('[data-pic]'); if (pic) return this.hooks.picture?.(pic.dataset.pic, pic.dataset.cap);
      const m = e.target.closest('[data-mem]');
      if (m && !m.disabled) { return this.go({ tab: this.s.tab === 'log' ? 'log' : this.s.tab, memory: m.dataset.mem }); }
      if (e.target.closest('[data-back]')) return this.hooks.leave ? this.hooks.leave() : this.go({ tab: this.s.tab, memory: null });
      const f = e.target.closest('[data-filter]'); if (f) { this.s.filter = f.dataset.filter; this.s.shown = PAGE; return this.render(); }
      const s = e.target.closest('[data-sort]'); if (s) { this.s.sort = s.dataset.sort; this.s.shown = PAGE; return this.render(); }
      const k = e.target.closest('[data-qkind]'); if (k) { this.s.qkind = this.s.qkind === k.dataset.qkind ? 'all' : k.dataset.qkind; this.s.shown = PAGE; return this.render(); }
      const h = e.target.closest('[data-hour]'); if (h && this.hooks.hour) return this.hooks.hour(h.dataset.hour);
    });
    body.addEventListener('change', (e) => {
      if (e.target.hasAttribute('data-hours-runner')) { this.hours = { ...this.currentHours(), runner: e.target.value, model: '' }; this.notices.delete('hours'); return this.render(); }
      if (e.target.dataset?.sortSelect) { this.s.sort = e.target.value; this.s.shown = PAGE; this.render(); } });
    body.addEventListener('keydown', (e) => {
      // ⌘↩ or Ctrl↩ sends what you wrote
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && e.target.dataset?.draft) {
        e.preventDefault();
        const k = e.target.dataset.draft;
        if (k === 'shared-new') this.sharedAdd(); else if (k.startsWith('fix:')) this.find('[data-fix-save]:not([disabled])')?.click(); else this.send(k);
      }
      if (e.key === 'Escape' && this.editing) { this.editing = null; this.render(); }
      if (e.key === 'Enter' && e.target.dataset?.jevKey) { e.preventDefault(); this.find('[data-jev-save]:not([disabled])')?.click(); }
    });
    body.addEventListener('input', (e) => {
      if (e.target.dataset?.jevKey) {
        this.jevKey = e.target.value;
        const save = this.find('[data-jev-save]'); if (save) save.disabled = !this.jevKey.trim() || this.sending === 'jev';
        return;
      }
      const time = e.target.dataset?.hoursTime;
      const model = e.target.hasAttribute('data-hours-model');
      if (time || model) {
        // the field keeps its focus: only the Save button and the hint change while you set a time
        this.hours = { ...this.currentHours(), [model ? 'model' : time]: e.target.value };
        const save = this.find('[data-hours-save]'); if (save) save.disabled = false;
        const hint = this.find('.set .acts .hint'); if (hint) { hint.textContent = 'Not saved yet.'; hint.classList.remove('flag'); }
        return;
      }
      if (e.target.dataset?.sharedAuthor) { this.shared.author = e.target.value; this.shared.shown = 50; this.render(); this.find('[data-shared-author]')?.focus(); return; }
      const key = e.target.dataset?.draft;
      if (key) {
        this.drafts.set(key, e.target.value);
        if (key === 'shared-new') { this.find('[data-shared-add]').disabled = !e.target.value.trim() || !!this.sending; return; }
        const send = this.find(`[data-send="${CSS.escape(key)}"]`);
        if (send) send.disabled = !e.target.value.trim() || this.sending === key;
        if (key.startsWith('fix:')) {
          const id = key.slice(4), m = this.s.tab === 'shared' ? this.ctx().life.shared.rows.find(m => m.id === id) : this.ctx().mems[this.ctx().byId.get(id)], save = this.find('[data-fix-save]');
          if (save && m) save.disabled = !e.target.value.trim() || e.target.value.trim() === m.content.trim();
        }
        return;
      }
      if (e.target.id !== 'room-search') return;
      if (this.s.tab === 'shared') { this.shared.query = e.target.value; this.shared.shown = 50; return this.render(); }
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
  restoreOpen() { for (const root of [this.bodyEl, this.hooks.pane?.el]) for (const d of root?.querySelectorAll('details[data-key]') || []) if (this.whole.has(d.dataset.key)) d.open = true; }
}

/* one route for both views: #read/<tab> or #read/memory/<id> */
export function parseRoute(hash, tabs) {
  const m = (hash || '').match(/^#read\/(memory\/(.+)|(\w+))$/);
  if (!m) return null;
  if (m[2]) return { memory: decodeURIComponent(m[2]) };
  return tabs.includes(m[3]) ? { tab: m[3] } : null;
}
