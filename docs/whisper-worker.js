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

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "load") {
      await load(data.device);
      postMessage({ type: "ready", device });
    } else if (data.type === "transcribe") {
      await load(data.device);
      const t0 = performance.now();
      const out = await asr(data.audio, {
        language: "greek",
        task: "transcribe",
        chunk_length_s: 30,
        stride_length_s: 5,
      });
      postMessage({
        type: "result", id: data.id, text: (out.text || "").trim(),
        seconds: (performance.now() - t0) / 1000, device,
      });
    }
  } catch (e) {
    postMessage({ type: "error", id: data.id, message: String(e?.message || e) });
  }
};
