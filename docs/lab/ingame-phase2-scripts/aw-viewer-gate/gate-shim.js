/*
 * gate-shim.js — the capture contract, ported from build-world's kit onto
 * agent-world's viewer page (prismarine-viewer's client). Runs in the page,
 * dropped in by the run_aw_gate.sh recipe. This is PROTOTYPE code: it stands up
 * the contract on the renderer we actually have, not on a toy.
 *
 * …and the renderer we actually have exposes no handle at all. The bundle's ONLY
 * global is `window.__THREE__`, which in three.js is the REVISION string (the
 * multi-instance marker), not the namespace: no window.THREE, no webpack chunk
 * registry on the page, no exported module. So the kit's trick of wrapping
 * `THREE.WebGLRenderer.prototype.render` is impossible here and the shim
 * instruments at the seams that ARE public:
 *
 *  frame/settle/RENDER_INFO -> the WebGL context the page creates (getContext
 *                              hook: draw calls, triangles, programs, buffers)
 *                              + a requestAnimationFrame wrap for frame bounds,
 *                              + LOCKSTEP (?lockstep=1: the client loop is held
 *                              after READY and advance only when the harness
 *                              pumps — the kit's contract 2 (`frame(); present();
 *                              screenshot`), without which the shutter races the
 *                              loop and a streamed world drifts between runs)
 *  camera posing for shots  -> the viewer's own OrbitControls input (pointer
 *                              drag = orbit, wheel = dolly). This bundle's
 *                              OrbitControls has no damping and no pointer
 *                              capture, so a drag lands on an EXACT spherical
 *                              pose one frame later. Shots track ABSOLUTE
 *                              deltas, so applying a shot twice is idempotent —
 *                              GC E's contract at the input seam instead of the
 *                              object seam.
 *
 * Page API (the kit's capture contract, as build-world's harness.mjs consumes it):
 *   window.__SHOTS__           named, reproducible framings
 *   window.__APPLY_SHOT__(s,f) pose + wait for the world to stop streaming + f
 *                              frames (the frame budget is the harness's pump)
 *   window.__PUMP__(n)         advance exactly n frames (lockstep) / wait n
 *                              frames (free-running)
 *   window.__PRESENT__(n)      yield to the compositor WITHOUT advancing frames
 *   window.__RENDER_INFO__     what the GL did: calls, triangles, programs, ...
 *   window.__READY__           true after 3 frames that actually drew something
 *
 * …plus the page's own knobs (GC C/D, the contract vg.js.yaml pins):
 *   ?tilt=1     every shot applies an extra orbit-up offset: the deliberate,
 *               view-visible change the pixel gate must catch.
 *   ?lightdim=1 kept for parity with the GLB page (not used by this view).
 */
(() => {
  if (window.__GATE_SHIM__) return;
  window.__GATE_SHIM__ = true;

  const params = new URLSearchParams(location.search);
  const forced = params.get('tilt') === '1' ? 1 : 0;
  const wantLockstep = params.get('lockstep') === '1';
  // Every screenshot the harness takes is a PAGE screenshot: the viewer's own
  // DOM banner (the "draws 26.1 as 1.21.4" notice, the coords strip) is part of
  // the pixels and it FADES with wall-clock time — a free variable the pixel
  // gate cannot tolerate. Under ?capture=1 the shim keeps only what draws the
  // canvas (its ancestor chain) and hides every other element, including ones
  // injected later (the notice appears after the assets resolve).
  if (params.get('capture') === '1') {
    const keep = (el) =>
      !!el && typeof el.tagName === 'string' &&
      (el.tagName === 'CANVAS' || (!!el.querySelector && !!el.querySelector('canvas')));
    const showChain = (el) => {
      for (let n = el; n && n !== document.body; n = n.parentElement) {
        n.style.removeProperty('display');
      }
    };
    const hide = (el) => {
      if (!el || el.nodeType !== 1) return;
      if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return;
      if (keep(el)) {
        // the canvas (or its wrapper) must stay visible even if we hid an empty
        // wrapper earlier and the client appended the canvas into it later.
        showChain(el);
        return;
      }
      el.style.setProperty('display', 'none', 'important');
    };
    for (const el of Array.from(document.body.children)) hide(el);
    new MutationObserver((muts) => {
      for (const m of muts) for (const n of m.addedNodes) hide(n);
    }).observe(document.body, { childList: true, subtree: true });
  }
  const stats = {
    calls: 0,
    triangles: 0,
    programs: 0,
    geometries: 0,
    textures: 0,
    drawnFrames: 0,
    frames: 0,
    locked: false,
    tilt: forced,
    seam: 'webgl-context + orbit-input', // THREE itself is unreachable (REVISION string only)
  };
  let frameCalls = 0;
  let frameTris = 0;
  let locked = false; // set at READY when ?lockstep=1

  // --- frame bookkeeping: every client-loop frame passes our rAF wrap ---------
  function endFrame() {
    stats.frames += 1;
    if (frameCalls > 0) {
      stats.drawnFrames += 1;
      stats.calls += frameCalls;
      stats.triangles += frameTris;
      if (stats.drawnFrames >= 3 && window.__READY__ !== true) {
        window.__READY__ = true;
        // D2: from READY on, the loop must not advance on its own.
        if (wantLockstep) {
          locked = true;
          stats.locked = true;
        }
        console.info(
          'gate-shim: ready after ' + stats.drawnFrames + ' drawn frames, lockstep=' + locked
        );
      }
    }
    frameCalls = 0;
    frameTris = 0;
  }

  const origRaf = window.requestAnimationFrame.bind(window);
  const held = [];
  let rafId = 1;
  window.requestAnimationFrame = (cb) => {
    if (!locked) {
      return origRaf((t) => {
        endFrame(); // closes out the previous frame's draws
        return cb(t);
      });
    }
    held.push(cb);
    return (rafId += 1);
  };

  // one lockstep frame = run exactly one batch of held callbacks (the client's
  // loop re-registers inside, so the queue refills to one entry per frame).
  function releaseBatch() {
    return new Promise((resolve) => {
      const batch = held.splice(0, held.length);
      origRaf((t) => {
        endFrame();
        for (const cb of batch) cb(t);
        resolve();
      });
    });
  }

  const waitFrames = (n) =>
    new Promise((resolve) => {
      const target = stats.frames + Math.max(0, n | 0);
      const check = () => (stats.frames >= target ? resolve() : origRaf(check));
      check();
    });

  async function runFrames(n) {
    const count = Math.max(0, n | 0);
    if (!locked) return waitFrames(count);
    for (let i = 0; i < count; i += 1) await releaseBatch();
  }

  window.__PUMP__ = async (n) => {
    await runFrames(n);
    return { frames: n };
  };
  window.__PRESENT__ = (n) =>
    new Promise((r) => {
      let left = Math.max(1, n | 0);
      const step = () => (--left <= 0 ? r({ presented: n }) : origRaf(step));
      origRaf(step);
    });

  // The world STREAMS in (worker.js builds chunk meshes as they arrive), so a
  // fixed frame budget alone does not pin the scene: the shutter would catch a
  // different amount of world on each run. The worker's results arrive in
  // BURSTS with multi-frame gaps, so "a few quiet frames" is not enough (the
  // first attempt settled after ~300 buffers where the finished world needed
  // 3600+): settle = advance frames until the geometry count has been unchanged
  // for BOTH 30 consecutive frames AND 8 s of wall clock (bounded). Even then
  // the TOTALS differ page to page (3756…4464 buffers in one run): distant
  // chunks in waves with multi-second lulls. Shots whose frustum contains only
  // settled land reproduce to ~0.14 %; the shot over the pending far chunks
  // does not. That is a WORLD-MANIFEST problem, and it is exactly what
  // vibecode-in-world's D1 step has to pin (see the lab log).
  async function settleWorld({ stableFrames = 30, quietMs = 8000, cap = 1500 } = {}) {
    let stable = 0;
    let lastGeo = -1;
    let spent = 0;
    let lastGrowth = performance.now();
    while (spent < cap) {
      await runFrames(1);
      spent += 1;
      const now = performance.now();
      if (stats.geometries !== lastGeo) {
        stable = 0;
        lastGeo = stats.geometries;
        lastGrowth = now;
      } else {
        stable += 1;
      }
      if (stable >= stableFrames && now - lastGrowth >= quietMs) break;
    }
    return {
      stable,
      frames: spent,
      geometries: stats.geometries,
      quietOk: performance.now() - lastGrowth >= quietMs,
    };
  }

  // --- GL seam: count what the frame actually drew ---------------------------
  function instrumentGL(gl) {
    if (gl.__gateShim) return gl;
    gl.__gateShim = true;
    const wrap = (name, fn) => {
      const orig = gl[name];
      if (typeof orig === 'function') gl[name] = fn(orig);
    };
    wrap('drawElements', (orig) =>
      function (mode, count) {
        frameCalls += 1;
        if (mode === gl.TRIANGLES) frameTris += count / 3;
        else if (mode === gl.TRIANGLE_STRIP || mode === gl.TRIANGLE_FAN) frameTris += Math.max(0, count - 2);
        return orig.apply(this, arguments);
      }
    );
    wrap('drawArrays', (orig) =>
      function (mode, first, count) {
        frameCalls += 1;
        if (mode === gl.TRIANGLES) frameTris += count / 3;
        else if (mode === gl.TRIANGLE_STRIP || mode === gl.TRIANGLE_FAN) frameTris += Math.max(0, count - 2);
        return orig.apply(this, arguments);
      }
    );
    wrap('createProgram', (orig) =>
      function () {
        stats.programs += 1;
        return orig.apply(this, arguments);
      }
    );
    wrap('createBuffer', (orig) =>
      function () {
        stats.geometries += 1;
        return orig.apply(this, arguments);
      }
    );
    wrap('createTexture', (orig) =>
      function () {
        stats.textures += 1;
        return orig.apply(this, arguments);
      }
    );
    return gl;
  }
  const origGet = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, attrs) {
    const ctx = origGet.call(this, type, attrs);
    if (ctx && /^(webgl|webgl2|experimental-webgl)$/.test(String(type))) instrumentGL(ctx);
    return ctx;
  };

  // --- camera seam: the viewer's own OrbitControls input ---------------------
  // OrbitControls in this bundle: rotate = 2*pi*delta/clientHeight around the
  // watcher, wheel deltaY<0 = dolly IN (getZoomScale = 0.95 per notch), and
  // update() lands the spherical pose EXACTLY one frame later (no damping).
  // Shots are therefore (orbitX px, orbitY px, dollyNotches) in ABSOLUTE terms;
  // the shim keeps the applied state and only sends the difference (idempotent).
  const state = { dx: 0, dy: 0, zoom: 0 };
  window.__GATE_STATE__ = state;

  function canvasEl() {
    return document.querySelector('canvas') || document.body;
  }
  function pointer(type, x, y) {
    canvasEl().dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        composed: true,
        pointerId: 1,
        pointerType: 'mouse',
        isPrimary: true,
        button: 0,
        buttons: type === 'pointerup' ? 0 : 1,
        clientX: x,
        clientY: y,
        view: window,
      })
    );
  }
  function dragBy(dx, dy) {
    if (!dx && !dy) return;
    const c = canvasEl();
    const x = Math.round((c.clientWidth || 960) / 2);
    const y = Math.round((c.clientHeight || 540) / 2);
    pointer('pointerdown', x, y);
    pointer('pointermove', x + dx, y + dy);
    pointer('pointerup', x + dx, y + dy);
  }
  function wheelNotches(n) {
    // deltaY < 0 === dolly in
    for (let i = 0; i < Math.abs(n); i += 1) {
      canvasEl().dispatchEvent(
        new WheelEvent('wheel', {
          bubbles: true,
          cancelable: true,
          deltaMode: 0,
          deltaY: n > 0 ? -100 : 100,
          clientX: 480,
          clientY: 270,
          view: window,
        })
      );
    }
  }

  // Named framings: absolute (orbit px around the watcher, dolly notches in).
  // The ?tilt=1 knob adds a fixed orbit-up to EVERY shot: a deliberate,
  // view-visible change the pixel gate must catch.
  const TILT0 = 120;
  const SHOTS = {
    'watcher-wide': { dx: 0, dy: 0, zoom: 0 },
    'watcher-detail': { dx: 120, dy: 60, zoom: 3 },
    'watcher-tilt': { dx: 40, dy: 150, zoom: 1 },
  };
  function targetOf(name) {
    const t = SHOTS[name];
    if (!t) return null;
    return forced ? { dx: t.dx, dy: t.dy + TILT0, zoom: t.zoom } : t;
  }

  async function applyShot(name, settle) {
    const target = targetOf(name);
    if (!target) return { unknown: name };
    dragBy(target.dx - state.dx, target.dy - state.dy);
    wheelNotches(target.zoom - state.zoom);
    state.dx = target.dx;
    state.dy = target.dy;
    state.zoom = target.zoom;
    await runFrames(2); // the drag lands exactly one frame after it (no damping)
    const steady = await settleWorld(); // the streamed world stops growing first
    await runFrames(1); // one guaranteed frame of the finished scene
    return { shot: name, ...target, tilt: forced, steady, settleRequested: settle ?? null };
  }

  Object.defineProperty(window, '__SHOTS__', {
    get: () =>
      Object.fromEntries(Object.keys(SHOTS).map((s) => [s, { ...targetOf(s), seam: 'orbit-input' }])),
  });
  window.__APPLY_SHOT__ = applyShot;
  Object.defineProperty(window, '__RENDER_INFO__', {
    get: () => ({ ...stats, camera: 'unreachable (window.__THREE__ is the REVISION string)' }),
  });

  window.__READY__ = false;
  console.info('gate-shim: loaded, tilt=' + forced + ', seam=' + stats.seam);
})();