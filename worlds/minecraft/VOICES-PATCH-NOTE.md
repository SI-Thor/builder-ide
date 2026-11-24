# The agent-world seat: one voice per agent, everywhere

**This is a patch note, not a patch.** Nothing in the Thor's repository has
been changed. The agent-world voices page is still speaking with Kokoro-82M,
exactly as it was. This file is the instruction set for whoever owns that
page, plus the measurements from the other side of the wire.

The page is `http://192.168.0.78:8080/voices` (the Express server that also
serves the Prismarine viewer at `/`).

---

## 1. What is being proposed

The first mile on the ProArt speaks the same four agents the agent-world
page speaks, with three different models:

| where | model | licence | bytes the page must fetch |
|---|---|---|---|
| rung 1, the ProArt's CPU | Paradee-8M-v1.2 (int8 ONNX) | Apache-2.0 | 8.1 MB + 4 KB vocab |
| rung 2, the ProArt's CPU | Audio8 0.1B INT8 ONNX | Apache-2.0 | — |
| rung 3, the ProArt's 4050 | Audio8 Realistic 0.6B | Apache-2.0 | — |
| rung 4, the ProArt's 4050 | LFM3-Audio-2B | LFM Open | — |

The agent-world page speaks the routine with Kokoro-82M **in the browser**,
so the Orin's Firefox needs no server at all. The proposal keeps that
property and swaps the engine for Paradee-8M, so that the same four voices
are the same four voices on the ProArt.

**The mechanism that makes this cheap.** Paradee-8M was distilled from
Kokoro-82M and kept its voice names. The page's own map is

```js
const VOICES = {
  Pebble: 'af_heart',
  Timber: 'am_puck',
  Kite: 'bm_fable',
  Sprout: 'bf_isabella',
};
```

and those four ids are Paradee's four voices as well
(`models/paradee/config.json`: `["af_heart", "bf_isabella", "am_puck",
"bm_fable"]`). **The map does not change.** Only the engine does. That is
why "one voice per agent, everywhere" is a registry and not a rewrite.

---

## 2. The files to copy

Everything comes from the first-mile repository on the ProArt
(`/home/proart/lm-wt/first-mile`). The Thor's page already serves a
`/paradee/` prefix for its Kokoro mirror, so the same prefix can hold
these.

| source on the ProArt | copy to on the Thor | size | licence |
|---|---|---|---|
| `node_modules/onnxruntime-web/dist/ort.min.mjs` | `public/vendor/onnxruntime-web/dist/ort.min.mjs` | 364 KB | MIT (Microsoft) |
| `node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm` | `public/vendor/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm` | 15 MB | MIT |
| `node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.mjs` | `public/vendor/onnxruntime-web/dist/ort-wasm-simd-threaded.mjs` | 28 KB | MIT |
| `node_modules/phonemizer/dist/phonemizer.js` | `public/vendor/phonemizer/dist/phonemizer.js` | 1.3 MB | Apache-2.0 (see §6) |
| `models/paradee/paradee_int8.onnx` | `public/paradee/paradee_int8.onnx` | 8.1 MB | Apache-2.0 |
| `models/paradee/config.json` | `public/paradee/config.json` | 4 KB | Apache-2.0 |
| `web/voices.json` | `public/voices.json` | 3 KB | Apache-2.0 (our own file) |

**Total: 24.8 MB, against Kokoro's 92 MB.** The page gets *smaller*.

The Kokoro files under `/paradee/models/onnx-community/Kokoro-82M-v1.0-ONNX/`
and `/vendor/kokoro/` can stay on the Thor; they are just no longer fetched
by this page. If nothing else uses them, removing them saves 92 MB of
mirror.

---

## 3. The change to the page

Three edits in the `<script type="module">` block of `voices.html`.

### 3a. the engine

**Before**

```js
const { KokoroTTS, env } = await import('/vendor/kokoro/kokoro.web.js');
env.wasmPaths = '/vendor/transformers/';
tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
  dtype: 'q8',
  device: 'wasm',
});
```

**After**

```js
import * as ort from '/vendor/onnxruntime-web/dist/ort.min.mjs';
import { phonemize } from '/vendor/phonemizer/dist/phonemizer.js';

ort.env.wasm.wasmPaths = '/vendor/onnxruntime-web/dist/';

const config = await (await fetch('/paradee/config.json')).json();
const modelBuf = await (await fetch('/paradee/paradee_int8.onnx')).arrayBuffer();
tts = await ort.InferenceSession.create(modelBuf, {
  executionProviders: ['wasm'],
  graphOptimizationLevel: 'all',
});
```

The `fetch` interception block that redirected Hugging Face to the local
mirror can come out: the Paradee files are local by construction, so there
is no remote URL to redirect.

### 3b. the speaking

**Before**

```js
const made = await tts.generate(text, { voice });
const buffer = audioCtx.createBuffer(1, made.audio.length, made.sampling_rate);
buffer.copyToChannel(made.audio, 0);
```

**After**

```js
// Paradee's graph speaks one sentence at a time: the ids are
// [0, ...phonemes, 0] and the 0 is the sentence boundary.
const parts = await phonemize(text, 'en-us');
for (const part of parts) {
  const wave = await synthSentence(part, voice);
  const buffer = audioCtx.createBuffer(1, wave.length, 24000);
  buffer.copyToChannel(wave, 0);
  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(audioCtx.destination);
  source.start();
}
```

with the helpers from the first mile's own page
(`first-mile/web/paradee.html`), which are small and copyable verbatim:

```js
const MAX_PHONEMES = 510;
const VOCAB = config.vocab;

function idsFor(phonemes) {
  const chars = [...phonemes];
  const kept = chars.filter(c => VOCAB[c] !== undefined).slice(0, MAX_PHONEMES);
  const ids = [0, ...kept.map(c => VOCAB[c]), 0];
  return BigInt64Array.from(ids.map(v => BigInt(v)));
}

async function synthSentence(phonemes, voice) {
  const ids = idsFor(phonemes);
  const feeds = {
    input_ids: new ort.Tensor('int64', ids, [1, ids.length]),
    speed: new ort.Tensor('float32', Float32Array.from([1.0]), [1]),
    voice: new ort.Tensor('int64', BigInt64Array.from([BigInt(VOICES.indexOf(voice))]), [1]),
  };
  const out = await tts.run(feeds);
  const name = tts.outputNames[0];
  const tensor = out.get ? out.get(name) : out[name];
  return tensor.data;
}
```

Two things to watch:

* **The page is not cross-origin isolated**, so the wasm build runs
  single-threaded. That is why the numbers below are slower than the
  server's. It is still faster than Kokoro's first audio.
* **The phonemes must be inside Paradee's vocabulary.** The first mile
  checks this on both sides of the boundary: the 39 phoneme symbols of one
  sentence are 100% covered by Paradee's own 114-symbol vocabulary, in the
  Python path and in the wasm path alike. If a line ever comes back with
  fewer phonemes than it started with, the `kept` filter above dropped
  something.

### 3c. the voices

**Before**

```js
const VOICES = { Pebble: 'af_heart', Timber: 'am_puck', Kite: 'bm_fable', Sprout: 'bf_isabella' };
```

**After** — read the ids from the registry, and check the reference hash, so
the page says out loud which agents it is speaking:

```js
const registry = await (await fetch('/voices.json')).json();
const VOICES = {
  Pebble: registry.voices.af_heart.paradee_voice,
  Timber: registry.voices.am_puck.paradee_voice,
  Kite: registry.voices.bm_fable.paradee_voice,
  Sprout: registry.voices.bf_isabella.paradee_voice,
};
```

The four ids are the same four strings as before, so this change is
cosmetic today. It is worth doing anyway: the registry is the place where
the voice of an agent is *defined*, and a page that reads it cannot drift
away from the definition.

---

## 4. The registry

`web/voices.json` in the first-mile repository. It is the small, portable
half of the agent registry: the voice id, the Paradee voice, and the hash
of the synthetic reference.

```json
{
  "version": 1,
  "what": "one voice per agent: a Paradee reference, and the clone rung 3 makes from it",
  "reference": {
    "source": "synthetic: Paradee-8M-v1.2, spoken on the ProArt",
    "text": "The harbour wall took the tide twice last week, so I would not put more weight on the north span.",
    "hash_algorithm": "sha256 of the 24 kHz mono WAV",
    "sample_rate": 24000
  },
  "voices": {
    "af_heart": {
      "id": "af_heart",
      "agent": "Ariadne",
      "paradee_voice": "af_heart",
      "reference_sha256": "…",
      "reference_text": "The harbour wall took the tide twice last week, so I would not put more weight on the north span.",
      "reference_seconds": 5.65,
      "rung2_voice": "agent_af_heart",
      "rung3_voice": "af_heart",
      "licence": "Apache-2.0 (Paradee-8M-v1.2, sahilmahendrakar/Paradee-8M-v1.2)",
      "source": "synthetic: Paradee-8M-v1.2 on this machine"
    }
  }
}
```

(The file in the repository carries all four voices; one is shown here.)

**The reference audio itself is not published.** It is a file on the
ProArt, and the hash is there so a seat can check it has the same reference
rather than a similar one. A seat that wants its own clone makes it from
the same text in the same Paradee voice.

**No human audio is involved anywhere.** Every reference is a model
speaking the ship's computer's own lines. There is no recording of a
person in this pipeline, and no transcript of a person either.

---

## 5. What it costs, measured on the ProArt

Headless Chrome, one thread, the page not cross-origin isolated
(`first-mile/scripts/bench_chrome.py`):

| line | first audio | wall | audio | RTF |
|---|---|---|---|---|
| "On it." | **105 ms** | 105 ms | 1.23 s | 0.086 |
| "Queued. It is in tonight's plan." | 127 ms | 354 ms | 3.42 s | 0.103 |
| "The north pier is sturdier now." | 200 ms | 200 ms | 2.75 s | 0.073 |
| "Job task_3dcff63cf17f is done…" | 378 ms | 524 ms | 7.55 s | 0.069 |
| "The harbour wall took the tide twice…" | 347 ms | 577 ms | 7.08 s | 0.082 |

The model loads in the tab in **1806 ms**, once.

For comparison, the same page's Kokoro engine loads 92 MB and the first
audio is measured from the first `tts.generate()` call, which includes the
whole line.

**Why the browser is slower than the server.** The wasm build of ONNX
Runtime on one browser thread is about 3–5× slower than the native
onnxruntime build the CPU service uses: rung 1's server-side real-time
factor is 0.020 against 0.069–0.103 in the tab. The first audio is still
inside a fifth of a second, because Paradee speaks one sentence at a time
and the first sentence is ready long before the line is.

**What the page gets for it.** The same four agents, defined once, in a
registry both seats read; a payload a quarter the size; and a voice that
the ProArt can clone again at rung 3 without ever recording a person.

---

## 6. The licensing note

`phonemizer.js` is Apache-2.0, but it embeds **eSpeak NG**, which is
GPL-3.0-or-later. The eSpeak data is compiled into the JavaScript file
itself, so it ships with the page.

This matters for how the Thor's page is distributed. Serving a GPL-3.0
library over HTTP from a LAN page is a different question from linking it
into a distributed product. If the agent-world page stays an internal LAN
tool, the practical risk is low. If it is ever shipped to a user, the
eSpeak part needs a different arrangement — either a GPL-3.0 compatible
whole, or a phonemiser that is not GPL.

This is flagged rather than resolved: it is the seat's call, not ours.

---

## 7. What was not done

* The Thor's repository was not edited. The page still speaks with Kokoro.
* The Thor's services were not touched.
* No human audio was recorded, stored, or transmitted. The only audio in
  this pipeline is model-generated.
* The registry is published from the first mile; nothing is pushed to the
  Thor. Copying it is the seat's step.

---

## 8. The check to run after the patch

1. Open `http://192.168.0.78:8080/voices` in the Orin's Firefox.
2. Press "start the voices". The status line should read
   `model: paradee-8M int8 (wasm), voices af_heart, am_puck, bm_fable, bf_isabella`.
3. Wait for a build event. The caption should appear and the line should be
   spoken, with no request to any server for the speech itself.
4. Check the network tab: only the model, the vocabulary and the wasm
   runtime should have been fetched. **No** request for
   `/paradee/models/onnx-community/Kokoro-82M-v1.0-ONNX/` should appear.
5. The time to first audio should be in the same range as the table in §5
   (105–378 ms). Anything much slower means the wasm build is running with
   the wrong execution provider, or the page is cross-origin isolated and
   has lost its threads.
