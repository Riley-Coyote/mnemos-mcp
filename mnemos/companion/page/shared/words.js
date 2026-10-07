/* Small words, for the log and its reading room. Times are the viewer's own; names come from the export's identity
 * (the model that signs the memories, named as Mnemos names it). The frame speaks of the mind in the third person;
 * only its own words say "I". */

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const at = (iso) => (iso ? new Date(iso) : null);
const fmt = (d, o) => d.toLocaleString('en-US', o);
export const clock = (d) => fmt(d, { hour: 'numeric', minute: '2-digit' }).toLowerCase().replace(' ', ' ');
export const dayKey = (d) => fmt(d, { year: 'numeric', month: '2-digit', day: '2-digit' });
export function dayName(d) {
  const today = new Date(), yesterday = new Date(Date.now() - 864e5);
  if (dayKey(d) === dayKey(today)) return 'Today';
  if (dayKey(d) === dayKey(yesterday)) return 'Yesterday';
  return fmt(d, { weekday: 'long', day: 'numeric', month: 'long' });
}
export const longDay = (d) => fmt(d, { weekday: 'long', day: 'numeric', month: 'long' });
export const shortDay = (d) => fmt(d, { day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
export function ago(ms) {
  const m = Math.max(0, Math.round(ms / 6e4));
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = ms / 36e5;
  if (h < 24) return `${h < 10 ? h.toFixed(1).replace(/\.0$/, '') : Math.round(h)} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? 'a day ago' : `${d} days ago`;
}
export const plural = (n, one, many = `${one}s`) => `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
export const words = (n) => ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'][n] ?? n.toLocaleString('en-US');
export const putTo = (n) => (n ? `put to it ${n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`}` : 'not yet put to it');
// an ask carries its instructions after the question ("If it is, state it in one line…"); keep only the question
export const question = (p) => { const i = (p || '').indexOf('?'); return i > 0 ? p.slice(0, i + 1) : p || ''; };
export function firstLine(t, n = 140) {
  const s = (t || '').split('\n').find((l) => l.trim()) || '';
  return s.length > n ? s.slice(0, s.lastIndexOf(' ', n)) + '…' : s;
}
// folded, an entry shows whole paragraphs up to about `long` characters, so it never stops mid-sentence
export function opening(text, long = 520) {
  const paras = (text || '').split(/\n{2,}/);
  let out = paras[0];
  for (const p of paras.slice(1)) { if ((out + p).length > long) break; out += '\n\n' + p; }
  return out.length > long * 1.6 ? out.slice(0, out.lastIndexOf(' ', long)) + ' …' : out;
}

// An entry's title is its own first sentence (or first line), set in the serif; what follows is its body, set to be
// read. Nothing is written for it: a long opening is cut at a clause, and the body carries on from exactly there.
export function titleOf(text) {
  const t = (text || '').trim();
  const line = t.split('\n')[0];
  const sentence = line.match(/^(.{1,160}?[.!?…]["'’”)\]]*)(?=\s|$)/);
  let title = sentence ? sentence[1] : line.length <= 120 ? line : '';
  if (!title) {
    const clause = line.slice(0, 110).match(/^(.{24,}?[,:;—])\s/);
    title = clause ? clause[1] : line.slice(0, line.lastIndexOf(' ', 90));
  }
  return { title, body: t.slice(title.length).trim() };
}

// the same naming Mnemos uses (mnemos.authorship.display_name): claude-opus-5-5 → Opus 5.5
export function modelName(model) {
  const m = (model || '').replace(/\[[^\]]*\]$/, '').split('/').pop().replace(/-\d{8}$/, '');
  let x = m.match(/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?$/);
  if (x) return `${x[1][0].toUpperCase()}${x[1].slice(1)} ${x[2]}${x[3] ? '.' + x[3] : ''}`;
  x = m.match(/^claude-(\d+)(?:-(\d{1,2}))?-([a-z]+)$/);
  if (x) return `${x[3][0].toUpperCase()}${x[3].slice(1)} ${x[1]}${x[2] ? '.' + x[2] : ''}`;
  return model || '';
}
export const sameModel = (a, b) => !!a && !!b && (a === b || modelName(a) === modelName(b));
export function signedBy(m, who) {
  if (m.model && sameModel(m.model, who.model)) return `signed ${who.name}`;
  if (m.model) return `written by ${modelName(m.model)}, a colleague`;
  if (m.author === 'agent') return `written by ${who.name} before memories were signed`;
  return 'no one can say who wrote it';
}
export const person = (who) => who.person || 'you';
export const forPerson = (who) => (who.person ? `for ${who.person}` : 'for you');

/* warmth: an hour's light, cooling since it ended (half-life six hours) */
export const HALF_LIFE_H = 6;
export const temperature = (h) => (h && h.end ? 2 ** (-(Date.now() - Date.parse(h.end)) / 36e5 / HALF_LIFE_H) : 0);
export function tempWord(k, h) {
  if (!h) return 'Cold';
  if (k >= 0.96) return 'White-hot';            // the first twenty minutes
  if (k >= 0.4) return 'Still warm';             // to about eight hours
  if (k >= 0.1) return 'Embers';                 // to about twenty
  return 'Cold';
}

export const KIND = { mine: 'Its own hour', ours: 'Our hour' };
export const KIND_LONG = { mine: 'Its own hour', ours: 'Our hour, for the day’s work' };
export const ASK = {
  lesson: ['What did it teach?', 'Memories fading, asked what they taught before they go.'],
  impact: ['What did it change?', 'Memories kept without saying what they changed.'],
  belief: ['A belief?', 'Asked from how often a word recurs. Kept out of its hours until they are grounded in meaning.'],
  reaffirm: ['Still true?', 'Beliefs it holds, asked again each month.'],
  // no longer asked; named only where an answered one stays in the history
  contradiction: ['A contradiction?', 'Two memories that may disagree. No longer asked.'],
};
export const ASK_ORDER = { lesson: 0, impact: 1, belief: 2, reaffirm: 3 };
export const RELATION = { co_activated: 'came back together', distilled_into: 'a lesson distilled from it', supports: 'supports it', contradicts: 'may contradict it' };

/* what an hour did, in a sentence, from its own record */
export function trailSentence(h, inMemory = null) {
  const t = h.trail || {};
  const woke = (t.woke || []).length, waiting = (t.waiting || []).length, reached = (t.reached || []).length;
  const memRefused = (h.refused || []).some((r) => /^mnemos_/.test(r));
  const parts = [];
  if (woke) parts.push(`woke with ${words(woke)} ${woke === 1 ? 'memory' : 'memories'} in hand`);
  if (waiting) parts.push(`found ${words(waiting)} ${waiting === 1 ? 'question' : 'questions'} waiting`);
  const tail = reached ? `reached for ${words(reached)}` : memRefused ? 'reached for none: its memory tools were refused that hour' : 'reached for none of its own';
  const s = `It ${parts.length ? parts.join(', ') + ', and ' : ''}${tail}.`;
  return inMemory === 0 && (woke || waiting || reached) ? `${s} None of it is in the memory shown here.` : s;
}
