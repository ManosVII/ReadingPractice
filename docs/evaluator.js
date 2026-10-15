/* Port of evaluator.py for the browser-only version.
 * SequenceMatcher reproduces Python's difflib.SequenceMatcher(None, a, b,
 * autojunk=False) so scores match the server version word for word. */

class SequenceMatcher {
  constructor(a, b) {
    this.a = a;
    this.b = b;
    this.b2j = new Map();
    b.forEach((w, j) => {
      if (!this.b2j.has(w)) this.b2j.set(w, []);
      this.b2j.get(w).push(j);
    });
    this._blocks = null;
  }

  findLongestMatch(alo, ahi, blo, bhi) {
    const { a, b, b2j } = this;
    let besti = alo, bestj = blo, bestsize = 0;
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map();
      for (const j of b2j.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestsize) { besti = i - k + 1; bestj = j - k + 1; bestsize = k; }
      }
      j2len = newj2len;
    }
    while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) {
      besti--; bestj--; bestsize++;
    }
    while (besti + bestsize < ahi && bestj + bestsize < bhi &&
           a[besti + bestsize] === b[bestj + bestsize]) {
      bestsize++;
    }
    return [besti, bestj, bestsize];
  }

  getMatchingBlocks() {
    if (this._blocks) return this._blocks;
    const la = this.a.length, lb = this.b.length;
    const queue = [[0, la, 0, lb]];
    const found = [];
    while (queue.length) {
      const [alo, ahi, blo, bhi] = queue.pop();
      const [i, j, k] = this.findLongestMatch(alo, ahi, blo, bhi);
      if (k) {
        found.push([i, j, k]);
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    found.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2]);
    const blocks = [];
    let i1 = 0, j1 = 0, k1 = 0;
    for (const [i2, j2, k2] of found) {
      if (i1 + k1 === i2 && j1 + k1 === j2) {
        k1 += k2;
      } else {
        if (k1) blocks.push([i1, j1, k1]);
        i1 = i2; j1 = j2; k1 = k2;
      }
    }
    if (k1) blocks.push([i1, j1, k1]);
    blocks.push([la, lb, 0]);
    this._blocks = blocks;
    return blocks;
  }

  getOpcodes() {
    let i = 0, j = 0;
    const answer = [];
    for (const [ai, bj, size] of this.getMatchingBlocks()) {
      let tag = "";
      if (i < ai && j < bj) tag = "replace";
      else if (i < ai) tag = "delete";
      else if (j < bj) tag = "insert";
      if (tag) answer.push([tag, i, ai, j, bj]);
      i = ai + size;
      j = bj + size;
      if (size) answer.push(["equal", ai, i, bj, j]);
    }
    return answer;
  }
}

function stripAccents(text) {
  return text.normalize("NFD").replace(/\p{Mn}/gu, "");
}

function normalizeText(text) {
  let t = stripAccents(text.toLowerCase());
  t = t.replace(/ς/g, "σ");                    // final sigma: same letter
  t = t.replace(/[^\p{L}\p{N}_\s]/gu, " ");
  return t.split(/\s+/).filter(Boolean).join(" ");
}

function tokenize(text) {
  const n = normalizeText(text);
  return n ? n.split(" ") : [];
}

/* ── Tolerant matching ─────────────────────────────────────────────────────
 * The browser recogniser often writes a correctly read word slightly
 * differently (one letter off, two words joined, a number as digits).
 * alignTranscript rewrites each heard word to the text's own word when the
 * difference is that small, so it is not counted as a reading mistake. */

function levenshtein(a, b, max) {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1,
                        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      rowMin = Math.min(rowMin, cur[j]);
    }
    if (rowMin > max) return max + 1;
    prev = cur;
  }
  return prev[b.length];
}

// How many letters may differ for a word of this length
function allowedEdits(len) {
  if (len <= 2) return 0;
  if (len <= 5) return 1;
  if (len <= 9) return 2;
  return 3;
}

function closestWord(word, vocab) {
  let best = null, bestD = Infinity;
  for (const w of vocab) {
    const max = allowedEdits(Math.max(w.length, word.length));
    let d = levenshtein(word, w, max);
    // Elided short words: «σ’», «τ’», «απ’» heard as «σε», «το», «απο»
    if (d > max && w.length <= 2 && word.startsWith(w) && word.length <= w.length + 2) d = 1;
    else if (d > max) continue;
    if (d < bestD) { best = w; bestD = d; }
  }
  return best;
}

const NUMBER_WORDS = {
  0: ["μηδεν"], 1: ["ενα", "μια", "ενασ", "εναν"], 2: ["δυο"], 3: ["τρια", "τρεισ"],
  4: ["τεσσερα", "τεσσερισ"], 5: ["πεντε"], 6: ["εξι"], 7: ["επτα", "εφτα"],
  8: ["οκτω", "οχτω"], 9: ["εννεα", "εννια"], 10: ["δεκα"], 11: ["εντεκα"], 12: ["δωδεκα"],
  20: ["εικοσι"], 30: ["τριαντα"], 40: ["σαραντα"], 50: ["πενηντα"], 60: ["εξηντα"],
  70: ["εβδομηντα"], 80: ["ογδοντα"], 90: ["ενενηντα"], 100: ["εκατο"],
};

function numberToWords(n) {
  if (NUMBER_WORDS[n]) return [NUMBER_WORDS[n]];
  if (n > 12 && n < 20) return [["δεκα" + NUMBER_WORDS[n - 10][0]]];
  if (n > 20 && n < 100) return [NUMBER_WORDS[n - n % 10], NUMBER_WORDS[n % 10]];
  return null;
}

function alignTranscript(orig, trans) {
  const vocab = new Set(orig);
  const vocabList = [...vocab];
  const pairs = new Map();                       // "καλημερα" -> ["καλη", "μερα"]
  for (let i = 0; i + 1 < orig.length; i++) pairs.set(orig[i] + orig[i + 1], [orig[i], orig[i + 1]]);

  // Digits back to words, choosing the form the text uses
  const words = [];
  for (const t of trans) {
    const groups = /^\d+$/.test(t) && !vocab.has(t) ? numberToWords(parseInt(t, 10)) : null;
    if (!groups) { words.push(t); continue; }
    for (const forms of groups) words.push(forms.find(f => vocab.has(f)) || forms[0]);
  }

  const out = [];
  for (let i = 0; i < words.length; i++) {
    const t = words[i];
    if (vocab.has(t)) { out.push(t); continue; }
    const next = words[i + 1];
    if (next !== undefined && !vocab.has(next)) {
      const joined = t + next;                     // «καλή» «μέρα» -> «καλημέρα»
      const w = vocab.has(joined) ? joined : (joined.length > 5 ? closestWord(joined, vocabList) : null);
      if (w && levenshtein(joined, w, 1) <= 1) { out.push(w); i++; continue; }
    }
    const split = pairs.get(t);                    // «σένα» -> «σ» «ένα»
    if (split) { out.push(...split); continue; }
    const w = closestWord(t, vocabList);
    out.push(w || t);
  }

  // Second pass, word against word in place: «σε ένα» read for «σ’ ένα»,
  // «τρία» for «3», even when the heard word exists elsewhere in the text.
  for (const [op, i1, i2, j1, j2] of new SequenceMatcher(orig, out).getOpcodes()) {
    if (op !== "replace" || i2 - i1 !== j2 - j1) continue;
    for (let k = 0; k < i2 - i1; k++) {
      if (sameWord(out[j1 + k], orig[i1 + k])) out[j1 + k] = orig[i1 + k];
    }
  }
  return out;
}

function sameWord(heard, word) {
  const max = allowedEdits(Math.max(heard.length, word.length));
  if (levenshtein(heard, word, max) <= max) return true;
  if (word.length <= 2 && heard.startsWith(word) && heard.length <= word.length + 2) return true;
  if (/^\d+$/.test(word)) {
    const groups = numberToWords(parseInt(word, 10));
    if (groups && groups.length === 1 && groups[0].includes(heard)) return true;
  }
  return false;
}

function vocabHits(text, vocabSet) {
  return tokenize(text).filter(w => vocabSet.has(w)).length;
}

function buildDiff(orig, trans) {
  const result = [];
  const m = new SequenceMatcher(orig, trans);
  for (const [op, i1, i2] of m.getOpcodes()) {
    const status = op === "equal" ? "correct" : op === "replace" ? "wrong"
                 : op === "delete" ? "missing" : null;
    if (!status) continue;                       // extra words said: not shown
    for (const w of orig.slice(i1, i2)) result.push({ word: w.replace(/(.)σ$/, "$1ς"), status });
  }
  return result;
}

function countCorrect(orig, trans) {
  return new SequenceMatcher(orig, trans).getMatchingBlocks()
    .reduce((s, b) => s + b[2], 0);
}

const round1 = x => Math.round(x * 10) / 10;

function punctuationScore(original, transcribed) {
  const origMarks = (original.match(/[.!?;]/g) || []).length || 1;
  const transMarks = (transcribed.match(/[.!?;]/g) || []).length;
  return Math.max(0, 1 - Math.abs(1 - transMarks / origMarks));
}

function evaluateReading(original, transcribed, durationSeconds,
                         { wpm_target = 80, w_acc = 0.60, w_spd = 0.30, w_pun = 0.10 } = {},
                         scorePunctuation = true) {
  const orig = tokenize(original), trans = alignTranscript(orig, tokenize(transcribed));
  if (!orig.length) return { error: "Κενό κείμενο" };
  const correct = countCorrect(orig, trans);
  const accuracy = correct / orig.length;
  const wpm = durationSeconds > 0 ? correct / durationSeconds * 60 : 0;
  const speedNorm = Math.min(wpm / wpm_target, 1);
  // Whisper writes punctuation, so it is scored as in evaluator.py. The
  // Google recogniser does not; then its weight goes to accuracy.
  const punct = scorePunctuation ? punctuationScore(original, transcribed) : null;
  const overall = punct === null
    ? accuracy * (1 - w_spd) + speedNorm * w_spd
    : accuracy * w_acc + speedNorm * w_spd + punct * w_pun;
  return {
    word_accuracy: round1(accuracy * 100),
    wpm: round1(wpm),
    punctuation_score: punct === null ? null : round1(punct * 100),
    overall_score: round1(overall * 100),
    correct_words: correct,
    total_words: orig.length,
    diff_tokens: buildDiff(orig, trans),
  };
}

function evaluateWpmMode(original, transcribed, durationSeconds) {
  const orig = tokenize(original), trans = alignTranscript(orig, tokenize(transcribed));
  if (!orig.length) return { error: "Κενό κείμενο" };
  const correct = countCorrect(orig, trans);
  const wpm = durationSeconds > 0 ? correct / durationSeconds * 60 : 0;
  const accuracy = correct / orig.length;
  return {
    word_accuracy: round1(accuracy * 100),
    wpm: round1(wpm),
    overall_score: round1(accuracy * 100),
    correct_words: correct,
    total_words: orig.length,
    diff_tokens: buildDiff(orig, trans),
  };
}

if (typeof module !== "undefined") {
  module.exports = { SequenceMatcher, tokenize, alignTranscript, vocabHits, evaluateReading, evaluateWpmMode, buildDiff };
}
