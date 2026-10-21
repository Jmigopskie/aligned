// Alan the owl as a three.js model, built from the Guided-mode character sheet
// (img/Alan_GuidedMode-CharacterUpdated.zip). Coordinates were measured on that
// sheet: 450 sheet px = 1 unit, x centred on the body, y = 0 at the body's base.
// Face markings are painted on from the front, so the front view matches the 2D art.
import * as THREE from "three";

const C = {
  body: "#808080", face: "#E5E5E5", eye: "#FDFDFD", ink: "#000000",
  beak: "#FFE200", wing: "#4F4F4F", cap: "#ED1C24", board: "#C1272D",
  clip: "#A86B16", metal: "#777777",
};

// Two-tone cel ramp. With the lights in the viewer the lit tone is the exact hex.
const RAMP = new THREE.DataTexture(new Uint8Array([140, 255]), 2, 1, THREE.RedFormat);
RAMP.minFilter = RAMP.magFilter = THREE.NearestFilter;
RAMP.needsUpdate = true;
const mats = {};
const toon = (color) => (mats[color] ||= new THREE.MeshToonMaterial({ color, gradientMap: RAMP }));
const flat = (color) => (mats["flat" + color] ||= new THREE.MeshBasicMaterial({ color }));
const OUTLINE = new THREE.MeshBasicMaterial({ color: "#111111", side: THREE.BackSide });

// ---- body silhouette (radius, height), traced from the pixels of sheet 01 ---
const PROFILE = [
  [0, -0.03], [0.2, 0], [0.307, 0.089], [0.378, 0.133], [0.484, 0.222], [0.564, 0.311],
  [0.609, 0.4], [0.64, 0.489], [0.658, 0.578], [0.664, 0.667], [0.667, 0.756], [0.667, 0.889],
  [0.663, 1.0], [0.66, 1.111], [0.66, 1.289], [0.658, 1.378], [0.644, 1.467], [0.62, 1.556],
  [0.58, 1.644], [0.524, 1.733], [0.444, 1.822], [0.318, 1.911], [0.2, 1.958], [0, 1.99],
];
const DEPTH = 0.86; // front-to-back squash
const curve = new THREE.CatmullRomCurve3(PROFILE.map(([r, y]) => new THREE.Vector3(r, y, 0)), false, "centripetal");
const LATHE = curve.getPoints(90).map((p) => new THREE.Vector2(Math.max(0, p.x), p.y));
LATHE[0].x = LATHE[LATHE.length - 1].x = 0;

function radiusAt(y) {
  for (let i = 1; i < LATHE.length; i++) {
    const a = LATHE[i - 1], b = LATHE[i];
    if (y <= b.y) return a.x + (b.x - a.x) * ((y - a.y) / (b.y - a.y || 1));
  }
  return 0;
}

// Point on the front of the body and its outward normal.
function surface(x, y) {
  const r = radiusAt(y), dr = (radiusAt(y + 0.005) - radiusAt(y - 0.005)) / 0.01;
  const z = DEPTH * Math.sqrt(Math.max(r * r - x * x, 0));
  const n = new THREE.Vector3(x, -r * dr, z / (DEPTH * DEPTH)).normalize();
  return { p: new THREE.Vector3(x, y, z), n };
}
const FWD = new THREE.Vector3(0, 0, 1);
function place(obj, x, y, lift = 0) {
  const { p, n } = surface(x, y);
  obj.position.copy(p).addScaledVector(n, lift);
  obj.quaternion.setFromUnitVectors(FWD, n);
  return obj;
}

// Ellipsoid that tapers to a rounded point at its lower end: feathers and toes.
function leafGeometry() {
  const g = new THREE.SphereGeometry(1, 32, 24);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const y = p.getY(i);
    if (y < 0) { const f = 1 + 0.6 * y; p.setX(i, p.getX(i) * f); p.setZ(i, p.getZ(i) * f); }
  }
  g.computeVertexNormals();
  return g;
}
const LEAF = leafGeometry();
const SPHERE = new THREE.SphereGeometry(1, 32, 20);

function mesh(geo, mat, [sx, sy, sz] = [1, 1, 1]) {
  const m = new THREE.Mesh(geo, mat);
  m.scale.set(sx, sy, sz);
  return m;
}
function outlined(m, grow = 1.06) {
  const o = new THREE.Mesh(m.geometry, OUTLINE);
  o.scale.setScalar(grow);
  m.add(o);
  return m;
}

// ---- face paint: face disc, belly, eyes and expressions ---------------------
const MW = 1024, MH = 1536, RECT = new THREE.Vector4(-0.75, -0.1, 1.5, 2.25);
const S = MW / RECT.z / 450; // sheet px -> canvas px
const TX = MW / 2 - 955 * S, TY = ((RECT.y + RECT.w) / RECT.w) * MH - 970 * S;
const EYE_DX = 128, EYE_Y = 340;

function ellipsePath(ctx, x, y, rx, ry) {
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
}
function stroke(ctx, w, draw) {
  ctx.lineWidth = w; ctx.lineCap = ctx.lineJoin = "round"; ctx.strokeStyle = C.ink;
  ctx.beginPath(); draw(); ctx.stroke();
}

function drawEye(ctx, side, f) {
  const ex = 955 + side * EYE_DX, ey = EYE_Y;
  const mode = f.eyes === "wink" ? (side > 0 ? "happy" : "open") : f.eyes;
  ctx.save();
  if (mode === "doubt") {
    // Heavy lid across the top of each eye, sloping like the "doubtful" pose.
    const [y0, y1] = side < 0 ? [ey - 44, ey - 14] : [ey - 6, ey - 44];
    ctx.beginPath();
    ctx.moveTo(ex - 90, y0); ctx.lineTo(ex + 90, y1); ctx.lineTo(ex + 90, ey + 100); ctx.lineTo(ex - 90, ey + 100);
    ctx.clip();
  }
  ctx.fillStyle = C.eye;
  ellipsePath(ctx, ex, ey, 72, 78); ctx.fill();
  ellipsePath(ctx, ex, ey, 72, 78); ctx.clip();

  if (mode === "happy") {
    ctx.fillStyle = C.ink;
    ctx.beginPath();
    ctx.moveTo(ex - 46, ey + 20);
    ctx.quadraticCurveTo(ex, ey - 50, ex + 46, ey + 20);
    ctx.quadraticCurveTo(ex, ey - 16, ex - 46, ey + 20);
    ctx.fill();
    stroke(ctx, 7, () => { ctx.moveTo(ex - 46, ey + 20); ctx.quadraticCurveTo(ex, ey - 46, ex + 46, ey + 20); });
  } else if (mode === "closed" || f.blink) {
    stroke(ctx, 14, () => { ctx.moveTo(ex - 50, ey + 2); ctx.quadraticCurveTo(ex, ey + 30, ex + 50, ey + 2); });
  } else {
    const doubt = mode === "doubt", k = mode === "wide" ? 0.68 : 1;
    const px = ex - side * 11 * k + f.look[0] + (doubt ? -side * 6 : 0);
    const py = ey + f.look[1] + (doubt ? 16 : 0);
    ctx.fillStyle = C.ink;
    ellipsePath(ctx, px, py, 39 * k, 48 * k); ctx.fill();
    ctx.fillStyle = C.eye;
    ellipsePath(ctx, px - 23 * k, py - 28 * k, 14 * k, 14 * k); ctx.fill();
  }
  ctx.restore();

  if (mode === "doubt") {
    const [y0, y1] = side < 0 ? [ey - 44, ey - 14] : [ey - 6, ey - 44];
    stroke(ctx, 16, () => { ctx.moveTo(ex - 66, y0 + 2 * (side < 0 ? 4 : 1)); ctx.lineTo(ex + 66, y1 + (side < 0 ? 4 : 1)); });
    if (side < 0) stroke(ctx, 20, () => { ctx.moveTo(ex - 52, ey - 70); ctx.lineTo(ex + 46, ey - 96); });
    else stroke(ctx, 20, () => { ctx.moveTo(ex - 56, ey - 96); ctx.quadraticCurveTo(ex - 6, ey - 136, ex + 34, ey - 120); });
  }
}

function drawFace(ctx, f) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = C.body;
  ctx.fillRect(0, 0, MW, MH);
  ctx.setTransform(S, 0, 0, S, TX, TY);
  ctx.fillStyle = C.face;
  ctx.beginPath();
  ctx.moveTo(800, 212);
  ctx.quadraticCurveTo(958, 160, 1112, 212);
  ctx.bezierCurveTo(1190, 238, 1222, 300, 1216, 350);
  ctx.bezierCurveTo(1210, 445, 1085, 534, 955, 534);
  ctx.bezierCurveTo(825, 534, 700, 445, 694, 350);
  ctx.bezierCurveTo(688, 300, 720, 238, 800, 212);
  ctx.fill();
  ellipsePath(ctx, 955, 720, 193, 188); ctx.fill();
  drawEye(ctx, -1, f);
  drawEye(ctx, 1, f);
}

function bodyMaterial(maskTex) {
  const m = new THREE.MeshToonMaterial({ color: C.body, gradientMap: RAMP });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uMask = { value: maskTex };
    sh.uniforms.uRect = { value: RECT };
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vObjPos;\nvarying vec3 vObjN;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvObjPos = position;\nvObjN = normal;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform sampler2D uMask;\nuniform vec4 uRect;\nvarying vec3 vObjPos;\nvarying vec3 vObjN;")
      .replace("#include <color_fragment>", `#include <color_fragment>
        vec4 paint = texture2D(uMask, (vObjPos.xy - uRect.xy) / uRect.zw);
        diffuseColor.rgb = mix(diffuseColor.rgb, paint.rgb, smoothstep(0.0, 0.12, vObjN.z));`);
  };
  return m;
}

// ---- clipboard ---------------------------------------------------------------
function drawPaper(ctx) {
  const W = 500, H = 720, ink = "#111111";
  ctx.fillStyle = "#FFFFFF"; ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = ink; ctx.lineWidth = 12; ctx.strokeRect(6, 6, W - 12, H - 12);
  ctx.fillStyle = ink; ctx.lineWidth = 4; ctx.lineJoin = "round";
  ctx.font = '64px "Patrick Hand", "Segoe Print", cursive';
  ctx.textAlign = "center";
  ctx.strokeText("LESSON PLAN", W / 2, 128); ctx.fillText("LESSON PLAN", W / 2, 128);
  const line = (x0, y0, x1, y1, w) => stroke(ctx, w, () => { ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); });
  line(66, 168, 434, 160, 9);
  const shape = (fill, w, draw) => {
    ctx.fillStyle = fill; ctx.lineWidth = w; ctx.strokeStyle = ink; ctx.lineJoin = "round";
    ctx.beginPath(); draw(); ctx.fill(); ctx.stroke();
  };
  const rows = [260, 375, 490, 605], cx = 104;
  // check box
  shape("#22A33A", 7, () => ctx.roundRect(cx - 34, rows[0] - 34, 68, 68, 12));
  stroke(ctx, 8, () => { ctx.moveTo(cx - 18, rows[0]); ctx.lineTo(cx - 4, rows[0] + 15); ctx.lineTo(cx + 20, rows[0] - 15); });
  // open book
  shape("#D4520E", 6, () => ctx.roundRect(cx - 40, rows[1] - 28, 37, 58, 6));
  shape("#D4520E", 6, () => ctx.roundRect(cx + 3, rows[1] - 28, 37, 58, 6));
  // pencil
  ctx.save(); ctx.translate(cx, rows[2]); ctx.rotate(-Math.PI / 4);
  shape("#F7D23A", 6, () => ctx.rect(-26, -12, 52, 24));
  shape("#F48FB1", 6, () => ctx.roundRect(26, -12, 16, 24, 5));
  shape("#F3DDB3", 6, () => { ctx.moveTo(-26, -12); ctx.lineTo(-46, 0); ctx.lineTo(-26, 12); ctx.closePath(); });
  ctx.restore();
  // star
  shape("#FFE14D", 6, () => {
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 15 : 36;
      ctx.lineTo(cx + Math.cos(a) * r, rows[3] + 3 + Math.sin(a) * r);
    }
    ctx.closePath();
  });
  rows.forEach((y) => line(176, y + 4, 432, y - 2, 7));
}

function clipboard() {
  const g = new THREE.Group();
  g.add(outlined(new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.84, 0.035), toon(C.clip)), 1.025));
  const cv = document.createElement("canvas");
  cv.width = 500; cv.height = 720;
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  const paint = () => { drawPaper(cv.getContext("2d")); tex.needsUpdate = true; };
  paint();
  document.fonts?.load('64px "Patrick Hand"').then(paint, () => {});
  const paper = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.72), new THREE.MeshBasicMaterial({ map: tex }));
  paper.position.set(0, -0.03, 0.019);
  g.add(paper);
  const clip = outlined(mesh(new THREE.BoxGeometry(1, 1, 1), toon(C.metal), [0.3, 0.075, 0.04]), 1.08);
  clip.position.set(0, 0.41, 0.03);
  const hump = outlined(new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.04, 32), toon(C.metal)), 1.1);
  hump.rotation.x = Math.PI / 2;
  hump.position.set(0, 0.45, 0.03);
  const hole = new THREE.Mesh(new THREE.TorusGeometry(0.02, 0.008, 8, 24), flat(C.ink));
  hole.position.set(0, 0.455, 0.052);
  g.add(clip, hump, hole);
  return g;
}

// ---- wings ---------------------------------------------------------------------
function wing() {
  const g = new THREE.Group();
  const feathers = [1, 0.92, 0.84].map((len, i) => {
    const pivot = new THREE.Group();
    const f = mesh(LEAF, toon(C.wing), [0.21, 0.4 * len, 0.085]);
    f.position.set(0, -0.36 * len, -0.01 * i);
    pivot.add(f);
    g.add(pivot);
    return pivot;
  });
  const finger = new THREE.Group();
  // Starts inside the broad part of the wing so the finger grows out of it, no neck.
  const tip = mesh(LEAF, toon(C.wing), [0.085, 0.2, 0.065]);
  tip.position.y = -0.12;
  finger.add(tip);
  finger.position.set(0, -0.55, 0.02);
  g.add(finger);
  return { g, feathers, finger };
}

// ---- poses -----------------------------------------------------------------------
// Wing: [x, y, z, rotX, rotY, rotZ, feather spread, finger]. Board: [x, y, z, rotX, rotY, rotZ, scale].
// move: amplitudes of the looping motion each pose plays (frequencies are fixed in update()).
const HANG_L = [-0.57, 1.1, -0.04, 0, 0, -0.07, 0, 0];
const HANG_R = [0.57, 1.1, -0.04, 0, 0, 0.07, 0, 0];
const HOLD_R = [0.6, 0.98, 0.62, 0, 0, -1.22, 0.22, 1]; // across the belly, finger on the board
const UP_L = [-0.6, 1.12, 0.05, 0, 0, -2.52, 0.2, 0]; // raised, feathers fanned
const UP_R = [0.6, 1.12, 0.05, 0, 0, 2.52, 0.2, 0];
const OFF = [0, 0.62, 0.58, 0, 0, 0, 0];
const MOVES = ["sway", "hop", "flapL", "flapR", "shrug", "nod", "shake", "tilt", "write", "jab"];
const M = (o = {}) => MOVES.map((k) => o[k] ?? (k === "sway" ? 0.16 : 0));
const REST = {
  body: [0, 0], wL: HANG_L, wR: HANG_R, board: OFF, cap: [0, 0], glasses: [0], pen: [0],
  bulb: [0], spinner: [0], tuft: [1], look: [0, 0], move: M(), eyes: "open", beak: "normal",
};
const held = (x, y = 0.62, rz = 0) => [x, y, 0.58, 0, 0, rz, 1];
const P = (o) => ({ ...REST, tuft: [o.cap ? 0 : 1], ...o });

export const POSES = [
  // the ten looks on the character sheet, in sheet order
  { key: "idle", label: "Idle", spec: P({ move: M({ tilt: 0.03 }) }) },
  { key: "present", label: "Presenting", spec: P({ wR: HOLD_R, board: held(0.08, 0.66), move: M({ nod: 0.03 }) }) },
  { key: "point", label: "Pointing", spec: P({ wL: [-0.62, 1.05, 0.1, 0, 0, -1.77, 0, 1], wR: HOLD_R, board: held(0, 0.62, 0.35), cap: [1, -0.3], look: [-14, -10], move: M({ jab: 0.08 }) }) },
  { key: "think", label: "Thinking", spec: P({ wL: [-0.6, 0.55, 0.5, 0, 0, 2.23, 0.15, 1], wR: [0.62, 1.02, 0.08, 0, 0, 1.0, 0, 0], board: [0.98, 0.9, 0.25, 0, -0.15, 0.04, 1], cap: [1, 0], look: [0, -14], move: M({ sway: 0.1, tilt: 0.05 }) }) },
  { key: "doubt", label: "Doubtful", spec: P({ body: [0.3, -0.14], wR: HOLD_R, board: held(0.18), cap: [1, 0.42], eyes: "doubt", move: M({ sway: 0.05, shake: 0.12 }) }) },
  { key: "celebrate", label: "Celebrating", spec: P({ wL: UP_L, wR: [0.62, 1.15, 0.05, 0, 0, 2.3, 0, 0], board: [1.0, 1.38, 0.25, 0, -0.2, 0.05, 1], cap: [1, 0], eyes: "happy", beak: "laugh", move: M({ hop: 0.1, flapL: 0.22 }) }) },
  { key: "wave", label: "Waving", spec: P({ wL: UP_L, wR: HOLD_R, board: held(0.17, 0.6), cap: [1, 0], eyes: "happy", move: M({ flapL: 0.28 }) }) },
  { key: "loading", label: "Loading", spec: P({ wR: HOLD_R, board: held(0.19, 0.6), cap: [1, -0.35], spinner: [1], look: [-18, 0], move: M({ tilt: 0.03 }) }) },
  { key: "check", label: "Checking", spec: P({ wL: [-0.6, 1.0, 0.3, 0, 0, -0.95, 0, 0], wR: [0.62, 0.95, 0.62, 0, 0, -1.0, 0, 1], board: [-0.62, 0.67, 0.45, 0, 0.2, 0.42, 1], cap: [1, 0], glasses: [1], pen: [1], look: [0, -16], move: M({ nod: 0.02, write: 0.06 }) }) },
  { key: "idea", label: "Idea", spec: P({ wL: [-0.62, 1.08, 0.1, 0, 0, -1.94, 0, 1], wR: HOLD_R, board: held(0.14, 0.56), cap: [1, -0.2], bulb: [1], look: [-10, -16], move: M({ hop: 0.05, jab: 0.05 }) }) },
  { key: "proud", label: "Proud", spec: P({ wL: [-0.62, 0.98, 0.62, 0, 0, 1.25, 0, 0], wR: [0.62, 0.98, 0.64, 0, 0, -1.25, 0, 0], board: held(0, 0.62), cap: [1, 0], eyes: "happy", beak: "smile", move: M({ tilt: 0.07 }) }) },
  // more looks in the same style
  { key: "cheer", label: "Cheering", spec: P({ wL: UP_L, wR: UP_R, cap: [1, 0], eyes: "happy", beak: "laugh", move: M({ hop: 0.12, flapL: 0.25, flapR: 0.25 }) }) },
  { key: "hi", label: "Saying hi", spec: P({ wL: UP_L, cap: [1, 0], eyes: "happy", move: M({ flapL: 0.3 }) }) },
  { key: "wink", label: "Winking", spec: P({ wR: [0.6, 1.0, 0.25, 0, 0, 2.5, 0, 1], cap: [1, 0.15], eyes: "wink", beak: "smile", move: M({ tilt: 0.06 }) }) },
  { key: "surprised", label: "Surprised", spec: P({ wL: [-0.6, 1.05, 0.05, 0, 0, -0.6, 0.2, 0], wR: [0.6, 1.05, 0.05, 0, 0, 0.6, 0.2, 0], cap: [1, 0], eyes: "wide", beak: "laugh", move: M({ sway: 0.08, hop: 0.04 }) }) },
  { key: "reading", label: "Reading", spec: P({ wL: [-0.6, 0.95, 0.5, 0, 0, 0.88, 0, 0], wR: [0.6, 0.95, 0.5, 0, 0, -0.88, 0, 0], board: [0, 0.63, 0.68, -0.25, 0, 0, 1], cap: [1, 0], glasses: [1], look: [0, 24], move: M({ sway: 0.08, nod: 0.025 }) }) },
  { key: "unsure", label: "Unsure", spec: P({ body: [0, 0.06], wL: [-0.62, 1.0, 0.05, 0, 0, -1.75, 0.25, 0], wR: [0.62, 1.0, 0.05, 0, 0, 1.75, 0.25, 0], cap: [1, -0.15], look: [-10, -18], move: M({ sway: 0.06, shrug: 0.18 }) }) },
  { key: "resting", label: "Resting", spec: P({ body: [0, 0.07], cap: [1, 0.25], eyes: "closed", move: M({ sway: 0.05, nod: 0.03 }) }) },
];

// ---- assembly --------------------------------------------------------------------
export function createAlan() {
  const root = new THREE.Group();
  const body = new THREE.Group(); // pivots at the base so tilts read as leaning
  root.add(body);

  const mask = document.createElement("canvas");
  mask.width = MW; mask.height = MH;
  const maskCtx = mask.getContext("2d");
  const maskTex = new THREE.CanvasTexture(mask);
  maskTex.colorSpace = THREE.SRGBColorSpace;
  maskTex.anisotropy = 8;
  const lathe = new THREE.LatheGeometry(LATHE, 128);
  lathe.scale(1, 1, DEPTH);
  body.add(new THREE.Mesh(lathe, bodyMaterial(maskTex)));

  // beak: yellow cap over a black hooked tip, plus the open and smiling variants
  const beak = {
    normal: new THREE.Group(), laugh: new THREE.Group(), smile: new THREE.Group(),
  };
  beak.normal.add(place(mesh(SPHERE, toon(C.beak), [0.095, 0.062, 0.07]), 0, 1.285, -0.01));
  const tip = mesh(new THREE.ConeGeometry(0.062, 0.13, 32), flat(C.ink));
  tip.rotation.x = Math.PI - 0.55;
  const tipHolder = place(new THREE.Group(), 0, 1.215, 0.035);
  tipHolder.add(tip);
  beak.normal.add(tipHolder);
  beak.laugh.add(place(mesh(LEAF, toon(C.beak), [0.1, 0.13, 0.075]), 0, 1.24, -0.005));
  beak.laugh.add(place(mesh(LEAF, flat(C.ink), [0.06, 0.06, 0.02]), 0, 1.2, 0.06));
  beak.smile.add(place(mesh(SPHERE, toon(C.beak), [0.12, 0.075, 0.07]), 0, 1.27, -0.01));
  const grin = new THREE.Mesh(new THREE.TorusGeometry(0.1, 0.014, 10, 32, Math.PI), flat(C.ink));
  grin.rotation.z = Math.PI;
  beak.smile.add(place(new THREE.Group(), 0, 1.3, 0.06).add(grin));
  Object.values(beak).forEach((b) => body.add(b));

  // head tuft (only shown without the cap)
  const tuft = new THREE.Group();
  const spike = (r, h, x, y, rz) => {
    const m = mesh(new THREE.ConeGeometry(r, h, 24), toon(C.body), [1, 1, 0.55]);
    m.position.set(x, y, 0); m.rotation.z = rz; tuft.add(m);
  };
  spike(0.075, 0.26, -0.05, 2.02, 0.2);
  spike(0.05, 0.16, 0.07, 1.98, -0.5);
  body.add(tuft);

  // feet (stay planted while the body leans)
  for (const side of [-1, 1]) {
    const foot = new THREE.Group();
    foot.add(mesh(SPHERE, toon(C.beak), [0.15, 0.065, 0.12]));
    [-0.09, 0, 0.09].forEach((x) => {
      const toe = mesh(SPHERE, toon(C.beak), [0.056, 0.05, 0.075]);
      toe.position.set(x, -0.015, 0.1 - Math.abs(x) * 0.3);
      foot.add(toe);
    });
    foot.position.set(side * 0.2, -0.02, 0.24);
    foot.rotation.y = side * 0.2;
    root.add(foot);
  }

  const wL = wing(), wR = wing();
  body.add(wL.g, wR.g);

  const board = clipboard();
  body.add(board);

  // mortarboard
  const cap = new THREE.Group();
  cap.position.set(0, 1.9, 0);
  const crownGeo = new THREE.CylinderGeometry(0.37, 0.39, 0.28, 64, 4, true);
  const cp = crownGeo.attributes.position;
  for (let i = 0; i < cp.count; i++) {
    const front = Math.max(0, cp.getZ(i) / 0.39);
    if (cp.getY(i) < -0.13) cp.setY(i, cp.getY(i) - 0.07 * front * front);
  }
  crownGeo.computeVertexNormals();
  const crown = new THREE.Mesh(crownGeo, toon(C.cap));
  crown.material.side = THREE.DoubleSide;
  crown.position.y = 0.08;
  const top = new THREE.Group();
  top.position.y = 0.25;
  top.rotation.x = 0.22;
  const plate = mesh(new THREE.BoxGeometry(1, 1, 1), toon(C.board), [0.93, 0.035, 0.93]);
  plate.rotation.y = Math.PI / 4;
  const corner = 0.93 / Math.SQRT2;
  const button = mesh(SPHERE, toon(C.board), [0.035, 0.03, 0.035]);
  button.position.y = 0.03;
  const cord = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, corner, 8), toon(C.board));
  cord.rotation.z = Math.PI / 2;
  cord.position.set(corner / 2, 0.025, 0);
  const drop = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.32, 8), toon(C.board));
  drop.position.set(corner, -0.16, 0);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.05, 0.022, 12, 32), toon(C.board));
  ring.position.set(corner, -0.36, 0);
  top.add(plate, button, cord, drop, ring);
  cap.add(crown, top);
  body.add(cap);

  // round glasses
  const glasses = new THREE.Group();
  for (const side of [-1, 1]) {
    const rim = place(new THREE.Group(), side * 0.284, 1.4, 0.07);
    rim.add(new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.024, 12, 64), flat(C.ink)));
    glasses.add(rim);
    const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.5, 8), flat(C.ink));
    arm.rotation.x = Math.PI / 2;
    arm.position.set(side * 0.5, 1.43, 0.2);
    glasses.add(arm);
  }
  const bridge = new THREE.Mesh(new THREE.TorusGeometry(0.06, 0.02, 8, 24, Math.PI), flat(C.ink));
  glasses.add(place(new THREE.Group(), 0, 1.43, 0.09).add(bridge));
  body.add(glasses);

  // pen for "checking"
  const pen = new THREE.Group();
  const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.032, 0.032, 0.48, 24), toon(C.metal));
  const nib = new THREE.Mesh(new THREE.ConeGeometry(0.032, 0.09, 24), toon(C.eye));
  nib.rotation.x = Math.PI; nib.position.y = -0.285;
  const capTop = new THREE.Mesh(new THREE.CylinderGeometry(0.034, 0.034, 0.07, 24), toon(C.eye));
  capTop.position.y = 0.2;
  pen.add(barrel, nib, capTop);
  pen.position.set(0.23, 0.64, 0.7);
  pen.rotation.z = -0.62;
  body.add(pen);

  // light bulb + "!" for "idea"
  const bulb = new THREE.Group();
  bulb.position.set(-1.0, 1.95, 0.25);
  bulb.add(mesh(SPHERE, flat("#FFF200"), [0.21, 0.22, 0.21]));
  const socket = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.07, 0.13, 24), toon(C.body));
  socket.position.y = -0.27;
  bulb.add(socket);
  [-0.6, 0, 0.6].forEach((a) => {
    const ray = new THREE.Mesh(new THREE.CapsuleGeometry(0.022, 0.09, 4, 8), flat("#FFE200"));
    ray.position.set(Math.sin(a) * 0.36, Math.cos(a) * 0.36, 0);
    ray.rotation.z = -a;
    bulb.add(ray);
  });
  const bang = new THREE.Mesh(new THREE.CapsuleGeometry(0.035, 0.16, 4, 12), flat(C.ink));
  bang.position.set(-0.42, 0.08, 0);
  bang.rotation.z = 0.15;
  const dot = mesh(SPHERE, flat(C.ink), [0.045, 0.045, 0.045]);
  dot.position.set(-0.47, -0.13, 0);
  bulb.add(bang, dot);
  root.add(bulb);

  // loading spinner: eight dots fading from dark to light
  const spinner = new THREE.Group();
  spinner.position.set(-0.98, 1.75, 0.2);
  for (let i = 0; i < 8; i++) {
    const shade = new THREE.Color("#333333").lerp(new THREE.Color("#BBBBBC"), i / 7);
    const d = mesh(SPHERE, flat("#" + shade.getHexString()), [0.055, 0.055, 0.055]);
    const a = Math.PI / 2 - (i * Math.PI) / 4;
    d.position.set(Math.cos(a) * 0.2, Math.sin(a) * 0.2, 0);
    spinner.add(d);
  }
  root.add(spinner);

  // ---- state & animation ----
  const NUM = ["body", "wL", "wR", "board", "cap", "glasses", "pen", "bulb", "spinner", "tuft", "look", "move"];
  const STILL = M({ sway: 0 });
  let target = POSES[0].spec;
  const cur = Object.fromEntries(NUM.map((k) => [k, [...target[k]]]));
  const face = { eyes: "open", look: [0, 0], blink: false };
  let painted = "", nextBlink = 2, blinkEnd = 0;

  const show = (obj, s) => { obj.visible = s > 0.02; obj.scale.setScalar(Math.max(s, 0.001)); };
  const applyWing = (w, a, extraZ) => {
    w.g.position.set(a[0], a[1], a[2]);
    w.g.rotation.set(a[3], a[4], a[5] + extraZ);
    w.feathers.forEach((f, i) => (f.rotation.z = a[6] * (i - 1)));
    show(w.finger, a[7]);
  };

  function setPose(key) {
    target = (POSES.find((p) => p.key === key) || POSES[0]).spec;
    face.eyes = target.eyes;
    Object.entries(beak).forEach(([k, g]) => (g.visible = k === target.beak));
  }

  function update(dt, t, calm = false) {
    const k = 1 - Math.exp(-dt * 7);
    for (const key of NUM) cur[key].forEach((v, i) => (cur[key][i] = v + (target[key][i] - v) * k));

    // Amplitudes blend between poses; frequencies stay fixed so the motion never jumps.
    const [sway, hop, flapL, flapR, shrug, nod, shake, tilt, write, jab] = calm ? STILL : cur.move;
    const flap = Math.sin(t * 7), lift = Math.sin(t * 2.2) * shrug;
    body.rotation.set(
      nod * Math.sin(t * 2.2),
      cur.body[0] + sway * Math.sin(t * 0.7) + shake * Math.sin(t * 1.6),
      cur.body[1] + tilt * Math.sin(t * 1.3)
    );
    body.scale.y = calm ? 1 : 1 + Math.sin(t * 1.8) * 0.008;
    root.position.y = hop * Math.abs(Math.sin(t * 4.5));
    applyWing(wL, cur.wL, flapL * flap + lift + jab * Math.sin(t * 5));
    applyWing(wR, cur.wR, -flapR * flap - lift + write * Math.sin(t * 10));
    const b = cur.board;
    board.position.set(b[0], b[1], b[2]);
    board.rotation.set(b[3], b[4], b[5]);
    show(board, b[6]);
    show(cap, cur.cap[0]);
    cap.rotation.z = cur.cap[1];
    cap.position.x = -cur.cap[1] * 0.18;
    show(glasses, cur.glasses[0]);
    show(pen, cur.pen[0]);
    show(bulb, cur.bulb[0]);
    show(spinner, cur.spinner[0]);
    show(tuft, cur.tuft[0]);
    if (!calm) {
      spinner.rotation.z = -Math.floor(t * 10) * (Math.PI / 4);
      bulb.position.y = 1.95 + Math.sin(t * 2.4) * 0.03;
    }

    // Reduced motion: Alan holds still, blinking included.
    if (!calm && t > nextBlink) { blinkEnd = t + 0.13; nextBlink = t + 2.5 + Math.random() * 3; }
    face.blink = face.eyes === "open" && t < blinkEnd;
    face.look = [Math.round(cur.look[0]), Math.round(cur.look[1])];
    const sig = `${face.eyes}|${face.blink}|${face.look}`;
    if (sig !== painted) { drawFace(maskCtx, face); maskTex.needsUpdate = true; painted = sig; }
  }

  setPose("idle");
  update(0, 0, true);
  return { root, setPose, update };
}
