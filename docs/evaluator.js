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

function buildDiff(orig, trans) {
  const result = [];
  const m = new SequenceMatcher(orig, trans);
  for (const [op, i1, i2] of m.getOpcodes()) {
    const status = op === "equal" ? "correct" : op === "replace" ? "wrong"
                 : op === "delete" ? "missing" : null;
    if (!status) continue;                       // extra words said: not shown
    for (const w of orig.slice(i1, i2)) result.push({ word: w.replace(/σ$/, "ς"), status });
  }
  return result;
}

function countCorrect(orig, trans) {
  return new SequenceMatcher(orig, trans).getMatchingBlocks()
    .reduce((s, b) => s + b[2], 0);
}

const round1 = x => Math.round(x * 10) / 10;

function evaluateReading(original, transcribed, durationSeconds,
                         { wpm_target = 80, w_spd = 0.30 } = {}) {
  const orig = tokenize(original), trans = tokenize(transcribed);
  if (!orig.length) return { error: "Κενό κείμενο" };
  const correct = countCorrect(orig, trans);
  const accuracy = correct / orig.length;
  const wpm = durationSeconds > 0 ? correct / durationSeconds * 60 : 0;
  const speedNorm = Math.min(wpm / wpm_target, 1);
  // The browser recogniser does not write punctuation, so punctuation is not
  // scored here; its weight goes to accuracy.
  const overall = accuracy * (1 - w_spd) + speedNorm * w_spd;
  return {
    word_accuracy: round1(accuracy * 100),
    wpm: round1(wpm),
    overall_score: round1(overall * 100),
    correct_words: correct,
    total_words: orig.length,
    diff_tokens: buildDiff(orig, trans),
  };
}

function evaluateWpmMode(original, transcribed, durationSeconds) {
  const orig = tokenize(original), trans = tokenize(transcribed);
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
  module.exports = { SequenceMatcher, tokenize, evaluateReading, evaluateWpmMode, buildDiff };
}
