// The throwaway Workers AI proxy for the clef delegate.
//
// It holds the AI binding and does one thing: run a model on an input and
// hand the answer back, with the worker-internal time beside it. Nothing is
// deployed — this runs under `wrangler dev --remote`, so the model inference
// happens at Cloudflare's edge and the worker's lifetime is the session.
//
// The body is {"model": ..., "input": {...}}; the input is the System One
// shape that clef-flash takes: a state, a schema of typed questions, and up
// to four images as data URLs.
export default {
  async fetch(req, env) {
    const body = await req.json();
    const t = Date.now();
    try {
      const out = await env.AI.run(
        body.model || "@cf/cloudflare/clef-flash",
        body.input,
      );
      return Response.json({ ms: Date.now() - t, out });
    } catch (e) {
      return Response.json({ ms: Date.now() - t, error: String(e) }, { status: 500 });
    }
  },
};
