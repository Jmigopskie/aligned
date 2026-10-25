// Alan peeking in on the sign-in, sign-up and password reset pages: every
// few seconds he slides in at a random spot on a random edge, does a random
// move (a wave, a think, a jump...), and slides back out. One Alan at a time,
// never over the form, hidden while someone types, and not at all when the
// device asks for reduced motion. The 3D model loads after the page, with the
// flat pictures as the fallback.

const MOVES = ["wave", "hi", "think", "cheer", "celebrate", "point", "idea", "wink", "surprised", "proud"];
const PNG_FOR = { wave: "wave", hi: "wave", think: "think", cheer: "celebrate", celebrate: "celebrate", point: "point", idea: "idea" };
const EDGES = ["left", "right", "bottom", "top"];
const QUIET_AFTER_TYPING = 4000;

const rand = (lo, hi) => lo + Math.random() * (hi - lo);
const pick = (list) => list[Math.floor(Math.random() * list.length)];

if (!matchMedia("(prefers-reduced-motion: reduce)").matches) start();

async function start() {
  const layer = document.createElement("div");
  layer.className = "alan-peek";
  layer.setAttribute("aria-hidden", "true");
  document.body.append(layer);

  const alan = (await load3D(layer)) || loadPictures(layer);
  const form = document.querySelector(".auth-panel");
  let size = 0, lastEdge = null, quietUntil = 0, shown = false, timer = 0;

  // Typing sends him away, and he stays away for a moment after.
  const hush = () => {
    quietUntil = Date.now() + QUIET_AFTER_TYPING;
    if (shown) hide();
  };
  document.addEventListener("input", hush, true);
  document.addEventListener("focusin", (e) => { if (e.target.matches("input, textarea")) hush(); });

  // Bigger on a big screen, never so big he crowds a phone.
  function fit() {
    size = Math.round(Math.min(330, Math.max(170, Math.min(innerWidth, innerHeight) * 0.38)));
    layer.style.width = layer.style.height = `${size}px`;
    alan.resize(size);
  }

  // Where he shows and where he hides for one edge, at a random point along
  // it; the transform turns him so his head always leans into the page.
  function spot(edge) {
    const W = innerWidth, H = innerHeight, S = size;
    if (edge === "left" || edge === "right") {
      const y = rand(H * 0.08, Math.max(H * 0.08, H * 0.92 - S));
      const lean = rand(18, 30) * (edge === "left" ? 1 : -1);
      // Head and a wing round the edge: enough to fit beside the form on the right too.
      const inX = edge === "left" ? -S * 0.58 : W - S * 0.42;
      const outX = edge === "left" ? -S * 1.15 : W + S * 0.15;
      return { show: [inX, y, lean], hide: [outX, y, lean], box: [Math.max(0, inX), y, Math.min(W, inX + S), y + S] };
    }
    const x = rand(W * 0.04, Math.max(W * 0.04, W * 0.96 - S));
    if (edge === "bottom") {
      const tilt = rand(-7, 7);
      return { show: [x, H - S * 0.6, tilt], hide: [x, H + S * 0.08, tilt], box: [x, H - S * 0.6, x + S, H] };
    }
    // From the top he hangs upside down.
    const tilt = 180 + rand(-8, 8);
    return { show: [x, -S * 0.42, tilt], hide: [x, -S * 1.12, tilt], box: [x, 0, x + S, S * 0.58] };
  }

  // Never over the form (with a margin), on any edge. A tilted square takes
  // more room than a straight one, so the box grows by what the tilt adds.
  function clearOfForm(box, deg) {
    if (!form) return true;
    const r = form.getBoundingClientRect();
    const a = (deg * Math.PI) / 180;
    const m = 12 + (size * (Math.abs(Math.sin(a)) + Math.abs(Math.cos(a)) - 1)) / 2;
    return box[2] < r.left - m || box[0] > r.right + m || box[3] < r.top - m || box[1] > r.bottom + m;
  }

  const place = ([x, y, r]) => { layer.style.transform = `translate(${x}px, ${y}px) rotate(${r}deg)`; };

  function hide() {
    shown = false;
    if (layer.dataset.hide) place(JSON.parse(layer.dataset.hide));
    setTimeout(() => { if (!shown) alan.stop(); }, 900);
    schedule(rand(6000, 10000));
  }

  function appear() {
    if (document.hidden || Date.now() < quietUntil) return schedule(2500);
    fit();
    let where = null;
    for (let i = 0; i < 16 && !where; i++) {
      const edge = pick(EDGES.filter((e) => e !== lastEdge));
      const s = spot(edge);
      if (clearOfForm(s.box, s.show[2])) where = { edge, ...s };
    }
    if (!where) return schedule(4000);
    lastEdge = where.edge;
    // Start out of sight, then slide in on the next frame.
    layer.style.transition = "none";
    place(where.hide);
    layer.dataset.hide = JSON.stringify(where.hide);
    alan.play(pick(MOVES));
    requestAnimationFrame(() => requestAnimationFrame(() => {
      layer.style.transition = "";
      place(where.show);
      shown = true;
      timer = setTimeout(() => shown && hide(), rand(2800, 3800));
    }));
  }

  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(appear, ms);
  }

  addEventListener("resize", () => { if (shown) hide(); });
  fit();
  layer.style.transform = "translate(-200vw, 0)";
  schedule(2200);
}

// The 3D Alan in a transparent canvas, drawn only while he's on screen.
async function load3D(layer) {
  try {
    const THREE = await import("three");
    const { createAlan } = await import("./alan3d.js?v=2026-10-26i");
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    const scene = new THREE.Scene();
    // Same lighting as the Guided stage: the toon ramp lands on the art's flat colours.
    scene.add(new THREE.AmbientLight(0xffffff, Math.PI * 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, Math.PI * 0.45);
    sun.position.set(-2, 4, 5);
    scene.add(sun);
    const model = createAlan();
    scene.add(model.root);
    // Framed with room for his widest props (the board, the light bulb).
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    camera.position.set(0, 1.2, 6.2);
    camera.lookAt(0, 1.1, 0);
    layer.append(renderer.domElement);

    const clock = new THREE.Clock();
    let running = false;
    const frame = () => {
      if (!running) return;
      model.update(Math.min(clock.getDelta(), 0.05), clock.elapsedTime);
      renderer.render(scene, camera);
      requestAnimationFrame(frame);
    };
    return {
      resize: (s) => renderer.setSize(s, s, false),
      play(move) {
        model.setPose(move);
        if (!running) {
          running = true;
          clock.getDelta();
          requestAnimationFrame(frame);
        }
      },
      stop() {
        running = false;
        model.setPose("idle");
      },
    };
  } catch (err) {
    return null;
  }
}

// No WebGL or no network for three.js: the flat pictures, peeking the same way.
function loadPictures(layer) {
  const img = Object.assign(document.createElement("img"), { alt: "", src: "img/owl/alan-wave.png" });
  layer.append(img);
  return {
    resize() {},
    play: (move) => { img.src = `img/owl/alan-${PNG_FOR[move] || "idle"}.png`; },
    stop() {},
  };
}
