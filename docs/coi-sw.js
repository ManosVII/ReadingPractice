/* Service worker that makes the page "cross-origin isolated".
 * GitHub Pages cannot send the COOP/COEP headers itself; without them the
 * browser allows only one CPU core for Whisper, which is several times
 * slower on computers without WebGPU. This worker adds the two headers. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.cache === "only-if-cached" && req.mode !== "same-origin") return;
  e.respondWith(
    fetch(req).then(res => {
      if (res.status === 0) return res;          // opaque response: pass through
      const headers = new Headers(res.headers);
      headers.set("Cross-Origin-Embedder-Policy", "credentialless");
      headers.set("Cross-Origin-Opener-Policy", "same-origin");
      return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
    })
  );
});
