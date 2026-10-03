// three.js viewer for parts: shaded body + CAD edges, deviation heat map, overlay of an aligned second part,
// and camera sync between side-by-side viewers.
import * as THREE from "three";
import { OrbitControls } from "./../vendor/OrbitControls.js";
import { binary } from "./api.js";

const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

export function parseMesh(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "PAM1") throw new Error("קובץ תצוגה לא תקין");
  const nv = dv.getUint32(4, true), nt = dv.getUint32(8, true), ne = dv.getUint32(12, true);
  const bbox = [...new Float32Array(buf.slice(16, 40))];
  let off = 40;
  const pos = new Float32Array(buf.slice(off, off + nv * 12)); off += nv * 12;
  const idx = new Uint32Array(buf.slice(off, off + nt * 12)); off += nt * 12;
  const edges = new Float32Array(buf.slice(off, off + ne * 12));
  return { pos, idx, edges, bbox, nv, nt };
}

export function parseCompare(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "PAC2") throw new Error("קובץ השוואה לא תקין");
  const na = dv.getUint32(4, true), nta = dv.getUint32(8, true), nb = dv.getUint32(12, true), ntb = dv.getUint32(16, true);
  const matrix = [...new Float32Array(buf.slice(20, 84))];
  const [max, p95, median, mirror] = new Float32Array(buf.slice(84, 100));
  let off = 100;
  const take = (n, nt) => {
    const pos = new Float32Array(buf.slice(off, off + n * 12)); off += n * 12;
    const idx = new Uint32Array(buf.slice(off, off + nt * 12)); off += nt * 12;
    const dev = new Float32Array(buf.slice(off, off + n * 4)); off += n * 4;
    return { pos, idx, dev };
  };
  const A = take(na, nta), B = take(nb, ntb);
  return { matrix, max, p95, median, mirror: mirror > 0.5, A, B };
}

// blue (0) -> green -> yellow -> orange -> red (max)
const STOPS = [[0, [0.18, 0.39, 0.78]], [0.25, [0.42, 0.77, 0.61]], [0.5, [0.96, 0.88, 0.37]], [0.75, [0.95, 0.66, 0.23]], [1, [0.75, 0.15, 0.18]]];
export function heatColor(t) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1], [t1, c1] = STOPS[i];
      const f = (t - t0) / (t1 - t0);
      return [c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f, c0[2] + (c1[2] - c0[2]) * f];
    }
  }
  return STOPS[STOPS.length - 1][1];
}

function buildObject(m, color) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3));
  g.setIndex(new THREE.BufferAttribute(m.idx, 1));
  g.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ color, metalness: 0.2, roughness: 0.55, polygonOffset: true,
    polygonOffsetFactor: 1, polygonOffsetUnits: 1, side: THREE.DoubleSide });
  const mesh = new THREE.Mesh(g, mat);
  const eg = new THREE.BufferGeometry();
  eg.setAttribute("position", new THREE.BufferAttribute(m.edges, 3));
  const edges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: css("--viewer-edge", "#2a3640") }));
  const grp = new THREE.Group();
  grp.add(mesh, edges);
  return { grp, mesh, edges, geom: g };
}

export class Viewer {
  constructor(el, { label = "", onCamera = null } = {}) {
    this.el = el;
    this.el.classList.add("viewer");
    this.el.innerHTML = `<div class="vmsg">טוען מודל…</div>${label ? `<div class="vlabel">${label}</div>` : ""}
      <div class="vtools"><button type="button" data-a="fit" title="התאם לתצוגה">מרכז</button><button type="button" data-a="edges" title="הצג/הסתר קווי מתאר">קווים</button></div>`;
    this.msg = el.querySelector(".vmsg");
    this.onCamera = onCamera;
    this.objects = [];
    this.syncing = false;
    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
    } catch (e) {
      this.msg.textContent = "הדפדפן לא תומך בתצוגה תלת-ממדית (WebGL)";
      this.failed = true;
      return;
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.el.prepend(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(css("--viewer-bg", "#eef1f1"));
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e6);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x5a6670, 1.15));
    const d1 = new THREE.DirectionalLight(0xffffff, 1.5); d1.position.set(1, 1.4, 1.2);
    const d2 = new THREE.DirectionalLight(0xffffff, 0.55); d2.position.set(-1.2, -0.4, -0.8);
    this.camera.add(d1, d2);
    this.scene.add(this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.addEventListener("change", () => { this.render(); if (!this.syncing && this.onCamera) this.onCamera(this); });
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.el);
    this.el.querySelector('[data-a="fit"]').onclick = () => { this.fit(); if (this.onCamera) this.onCamera(this); };
    this.el.querySelector('[data-a="edges"]').onclick = () => { this.objects.forEach((o) => (o.edges.visible = !o.edges.visible)); this.render(); };
    this.resize();
  }

  resize() {
    if (this.failed) return;
    const w = this.el.clientWidth || 300, h = this.el.clientHeight || 220;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.render();
  }

  render() { if (!this.failed) this.renderer.render(this.scene, this.camera); }

  async loadUrl(path, params) {
    if (this.failed) return null;
    try {
      const m = parseMesh(await binary(path, params));
      return this.setMesh(m);
    } catch (e) {
      this.msg.textContent = e.message || "לא ניתן להציג את המודל";
      this.msg.hidden = false;
      return null;
    }
  }

  setMesh(m, color = css("--viewer-part", "#b9c2c8")) {
    this.clear();
    const o = buildObject(m, color);
    this.scene.add(o.grp);
    this.objects.push(o);
    this.main = o;
    this.meshData = m;
    this.msg.hidden = true;
    this.fit();
    return o;
  }

  addOverlay(m, matrix, color = css("--brass", "#a9771a")) {
    const o = buildObject(m, color);
    o.mesh.material.transparent = true;
    o.mesh.material.opacity = 0.45;
    o.mesh.material.depthWrite = false;
    const M = new THREE.Matrix4().fromArray(matrix);
    o.grp.applyMatrix4(M);
    this.scene.add(o.grp);
    this.objects.push(o);
    this.render();
    return o;
  }

  // turn the part so it is seen like the reference part (rotation only: real size kept, never mirrored)
  orient(matrix) {
    if (!this.main || this.failed) return false;
    const M = new THREE.Matrix4().fromArray(matrix);
    if (M.determinant() <= 0) return false;
    const pos = new THREE.Vector3(), q = new THREE.Quaternion(), sc = new THREE.Vector3();
    M.decompose(pos, q, sc);
    this.main.grp.quaternion.copy(q);
    this.main.grp.updateMatrixWorld(true);
    this.fit();
    return true;
  }

  removeOverlays() {
    this.objects.filter((o) => o !== this.main).forEach((o) => { this.scene.remove(o.grp); o.geom.dispose(); });
    this.objects = this.main ? [this.main] : [];
    this.render();
  }

  // swap the shaded surface (e.g. for a refined copy that carries a deviation map); edges, pose and camera stay
  setSurface(pos, idx) {
    if (!this.main || this.failed) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.computeVertexNormals();
    this.main.mesh.geometry.dispose();
    this.main.mesh.geometry = g;
    this.main.geom = g;
    this.render();
  }

  heatmap(dev, max) {
    if (!this.main) return;
    const g = this.main.geom;
    const col = new Float32Array(dev.length * 3);
    const m = max > 0 ? max : 1;
    for (let i = 0; i < dev.length; i++) {
      const c = heatColor(dev[i] / m);
      col[3 * i] = c[0]; col[3 * i + 1] = c[1]; col[3 * i + 2] = c[2];
    }
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    this.main.mesh.material.vertexColors = true;
    this.main.mesh.material.color.set(0xffffff);
    this.main.mesh.material.needsUpdate = true;
    this.render();
  }

  plain() {
    if (!this.main) return;
    this.main.geom.deleteAttribute("color");
    this.main.mesh.material.vertexColors = false;
    this.main.mesh.material.color.set(css("--viewer-part", "#b9c2c8"));
    this.main.mesh.material.needsUpdate = true;
    this.render();
  }

  fit() {
    if (!this.main) return;
    const box = new THREE.Box3().setFromObject(this.main.mesh, true);  // precise: rotated parts get a tight box
    const sph = box.getBoundingSphere(new THREE.Sphere());
    this.radius = sph.radius || 1;
    this.controls.target.copy(sph.center);
    const dir = new THREE.Vector3(1, 0.75, 1.1).normalize();
    let dist = this.radius / Math.sin((this.camera.fov * Math.PI) / 360) * 1.15;
    this.camera.near = dist / 100; this.camera.far = dist * 100;
    // the bounding sphere leaves long thin parts small: move closer until the part fills ~72% of the view
    const pos = this.main.mesh.geometry.getAttribute("position");
    const step = Math.max(1, Math.floor(pos.count / 1500));
    const pt = new THREE.Vector3();
    for (let pass = 0; pass < 2; pass++) {
      this.camera.position.copy(sph.center).addScaledVector(dir, dist);
      this.camera.lookAt(sph.center);
      this.camera.updateMatrixWorld(true);
      this.camera.updateProjectionMatrix();
      let m = 0;
      for (let i = 0; i < pos.count; i += step) {
        pt.fromBufferAttribute(pos, i).applyMatrix4(this.main.mesh.matrixWorld).project(this.camera);
        m = Math.max(m, Math.abs(pt.x), Math.abs(pt.y));
      }
      if (!(m > 0.05)) break;
      dist *= Math.min(1.5, Math.max(0.35, m / 0.72));
    }
    this.camera.position.copy(sph.center).addScaledVector(dir, dist);
    this.camera.near = dist / 100; this.camera.far = dist * 100;
    this.radius = dist / (1.15 / Math.sin((this.camera.fov * Math.PI) / 360));  // keeps view() sync relative
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.render();
  }

  // camera state relative to the part (direction + distance in radii), so different parts sync sensibly
  view() {
    const off = this.camera.position.clone().sub(this.controls.target);
    return { dir: off.clone().normalize(), dist: off.length() / (this.radius || 1), up: this.camera.up.clone() };
  }
  setView(v) {
    if (!this.main || this.failed) return;
    this.syncing = true;
    this.camera.position.copy(this.controls.target).addScaledVector(v.dir, v.dist * (this.radius || 1));
    this.camera.up.copy(v.up);
    this.controls.update();
    this.syncing = false;
    this.render();
  }

  clear() {
    this.objects.forEach((o) => { this.scene.remove(o.grp); o.geom.dispose(); });
    this.objects = [];
    this.main = null;
  }

  dispose() {
    if (this.failed) return;
    this.ro.disconnect();
    this.clear();
    this.controls.dispose();
    this.renderer.dispose();
  }
}

// side-by-side viewers that follow each other's camera
export function linkViewers(viewers) {
  viewers.forEach((v) => {
    v.onCamera = (src) => { const st = src.view(); viewers.forEach((o) => o !== src && o.setView(st)); };
  });
}
