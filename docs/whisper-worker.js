/* Whisper speech recognition inside the browser (transformers.js).
 * Runs in a Web Worker so the page stays responsive. The model is downloaded
 * once from Hugging Face and then cached by the browser; audio never leaves
 * the computer. Same model size as the desktop app (WHISPER_MODEL "small"). */

import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1";

const MODEL = "onnx-community/whisper-small";

env.allowLocalModels = false;
env.useBrowserCache = true;
if (self.crossOriginIsolated) {
  // Several CPU cores for computers without WebGPU (see coi-sw.js)
  env.backends.onnx.wasm.numThreads = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1));
}

let asr = null;
let loading = null;
let device = "wasm";

async function hasWebGPU() {
  try {
    const adapter = await navigator.gpu?.requestAdapter();
    return !!adapter;
  } catch {
    return false;
  }
}

function makeProgress() {
  const files = new Map();
  let last = -1;
  return p => {
    if (p.status !== "progress" && p.status !== "done") return;
    const f = files.get(p.file) || { loaded: 0, total: 0 };
    if (p.total) f.total = p.total;
    f.loaded = p.status === "done" ? f.total : (p.loaded || 0);
    files.set(p.file, f);
    let loaded = 0, total = 0;
    for (const x of files.values()) { loaded += x.loaded; total += x.total; }
    const pct = total ? Math.floor(loaded / total * 100) : 0;
    if (pct !== last) {
      last = pct;
      postMessage({ type: "progress", pct, loadedMB: Math.round(loaded / 1e6), totalMB: Math.round(total / 1e6) });
    }
  };
}

async function build(dev) {
  const dtype = dev === "webgpu"
    ? { encoder_model: "q4", decoder_model_merged: "q4" }
    : { encoder_model: "q8", decoder_model_merged: "q8" };
  return pipeline("automatic-speech-recognition", MODEL, {
    device: dev, dtype, progress_callback: makeProgress(),
  });
}

async function load(prefer) {
  if (asr) return;
  if (!loading) {
    loading = (async () => {
      device = prefer === "wasm" ? "wasm" : (await hasWebGPU() ? "webgpu" : "wasm");
      try {
        asr = await build(device);
      } catch (e) {
        if (device !== "webgpu") throw e;
        device = "wasm";                    // GPU present but unusable: use the CPU
        asr = await build(device);
      }
      // Warm up so the first real reading is not slower than the rest
      await asr(new Float32Array(16000), { language: "greek", task: "transcribe" });
    })();
  }
  try {
    await loading;
  } catch (e) {
    loading = null;
    throw e;
  }
}

const SR = 16000;

// Cut points at the quietest 300 ms within 15–28 s of the previous cut
function splitAtPauses(x, maxSec = 28, minSec = 15) {
  const hop = 160, win = 30;                       // 10 ms frames, 300 ms window
  const n = Math.floor(x.length / hop);
  if (n * hop <= maxSec * SR) return [x];
  const energy = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let j = i * hop; j < (i + 1) * hop; j++) s += x[j] * x[j];
    energy[i] = s;
  }
  const smooth = new Float32Array(n);
  let acc = 0;
  for (let i = 0; i < n; i++) {
    acc += energy[i];
    if (i >= win) acc -= energy[i - win];
    smooth[i] = acc;
  }
  const cuts = [0];
  let start = 0;
  while ((n - start) * hop > maxSec * SR) {
    let best = start + maxSec * SR / hop, bestV = Infinity;
    for (let i = start + minSec * SR / hop; i < start + maxSec * SR / hop; i++) {
      if (smooth[i] < bestV) { bestV = smooth[i]; best = i - win / 2; }
    }
    start = Math.round(best);
    cuts.push(start);
  }
  cuts.push(n);
  const pieces = [];
  for (let i = 0; i + 1 < cuts.length; i++) {
    pieces.push(x.subarray(cuts[i] * hop, i + 2 === cuts.length ? x.length : cuts[i + 1] * hop));
  }
  return pieces;
}

function rms(x) {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return Math.sqrt(s / Math.max(1, x.length));
}

// Whisper sometimes gets stuck repeating a word or phrase ("το κουλίου, το
// κουλίου, ..."). Keep at most three in a row, as texts have («Πα Πα Πα»).
function collapseLoops(text) {
  const words = text.split(/\s+/).filter(Boolean);
  const out = [];
  for (let i = 0; i < words.length;) {
    let skipped = false;
    for (let len = 1; len <= 4 && !skipped; len++) {
      if (out.length < 3 * len) continue;
      const same = (a, b) => a.replace(/[^\p{L}\p{N}]/gu, "").toLowerCase() === b.replace(/[^\p{L}\p{N}]/gu, "").toLowerCase();
      const phrase = words.slice(i, i + len);
      if (phrase.length < len) continue;
      const prev = [1, 2, 3].map(r => out.slice(out.length - r * len, out.length - (r - 1) * len));
      if (phrase.every((w, k) => prev.every(p => same(w, p[k])))) { i += len; skipped = true; }
    }
    if (!skipped) out.push(words[i++]);
  }
  return out.join(" ");
}

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "load") {
      await load(data.device);
      postMessage({ type: "ready", device });
    } else if (data.type === "transcribe") {
      await load(data.device);
      const t0 = performance.now();
      // Whisper hears at most 30 s at a time. The pipeline's own chunking
      // (chunk_length_s) dropped whole chunks of long readings, so the
      // recording is cut at the quietest pauses and each piece is
      // transcribed on its own.
      const parts = [];
      for (const piece of splitAtPauses(data.audio)) {
        if (rms(piece) < 0.002) continue;          // silence: Whisper would invent text
        const out = await asr(piece, { language: "greek", task: "transcribe" });
        parts.push(collapseLoops((out.text || "").trim()));
      }
      postMessage({
        type: "result", id: data.id, text: parts.filter(Boolean).join(" "),
        seconds: (performance.now() - t0) / 1000, device,
      });
    }
  } catch (e) {
    postMessage({ type: "error", id: data.id, message: String(e?.message || e) });
  }
};
