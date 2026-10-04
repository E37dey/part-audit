// Pre-release check: before a part number is opened, a new part's STEP file is compared with every part of the last
// scan - the same file, the same shape (also in other units), a near-identical shape, a mirror image, the same
// standard part, a planned part number that is already taken.
import { get, send, binary, isStatic, uploadCheck } from "../api.js";
import { esc, n0, secs, date, datetime, pnChip, sysBadge, catPill, confBar, uidLink, statePill, ICON, dims, cm3 } from "../util.js";
import { toast, confirmInline } from "../ui.js";
import { compare3d } from "../compare3d.js";

const TONE_ICON = { bad: ICON.stop, warn: ICON.caution, ok: ICON.go, info: ICON.mirror };
const KIND_PILL = { exists: ["כבר קיים", "bad"], attr_conflict: ["אותה צורה, מפרט אחר", "warn"], near: ["כמעט זהה קיים", "warn"],
  mirror: ["גרסת ראי קיימת", "info"], new: ["חדש – לא נמצא", "ok"], no_geometry: ["נבדק בלי צורה", "warn"] };
const kb = (b) => (b == null ? "—" : b < 1e6 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1048576).toFixed(1)} MB`);

function verdictPill(c) {
  if (c.status === "running") return '<span class="pill neutral">רצה…</span>';
  if (c.status === "error") return '<span class="pill bad">נכשלה</span>';
  const [he, tone] = c.verdict?.kind === "new" && c.verdict?.tone === "warn" ? ["חדש – המק\"ט תפוס", "warn"]
    : KIND_PILL[c.verdict?.kind] || [c.verdict?.title || "—", "neutral"];
  return `<span class="pill ${tone}">${esc(he)}</span>`;
}

function history(rows) {
  if (!rows.length) return `<div class="empty">עדיין לא נבדקו חלקים. הבדיקות שתריצו יישמרו כאן.</div>`;
  return `<div class="table-wrap"><table class="t"><thead><tr><th>מתי</th><th>קובץ</th><th>מק"ט מתוכנן / שם</th><th>תוצאה</th><th>החלק הקיים</th></tr></thead>
    <tbody>${rows.map((c) => `<tr class="click" data-id="${esc(c.id)}"><td class="nowrap small">${datetime(c.at)}</td>
      <td><span class="mono small ltr">${esc(c.file)}</span>${c.sample ? ' <span class="pill neutral plain">דוגמה</span>' : ""}</td>
      <td>${c.input.pn ? pnChip(c.input.pn) + " " : ""}${esc(c.input.name || "")}</td>
      <td>${verdictPill(c)}</td><td>${c.use_pn ? pnChip(c.use_pn, c.verdict?.kind === "exists") : '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table></div>`;
}

async function intake({ el, state, setTitle, go }) {
  setTitle("בדיקת חלק חדש", "לפני שפותחים מק\"ט");
  const s = state.summary;
  if (!s && !isStatic) {
    el.innerHTML = `<section class="panel"><div class="empty stack" style="align-items:center">
      <p>הבדיקה משווה חלק חדש לכל החלקים שנסרקו, ולכן קודם צריך סריקה של המערכות.</p>
      <a class="btn primary" href="#/sources">למקורות הנתונים</a></div></section>`;
    return null;
  }
  const [rows, samples] = await Promise.all([get("/api/checks"), get("/api/checks/samples").catch(() => [])]);
  const sm = s?.summary;
  const scope = sm ? `הקובץ יושווה ל-${n0(sm.parts)} החלקים מהסריקה של ${date(s.created)}` : "הקובץ יושווה לחלקים מהסריקה האחרונה";
  el.innerHTML = `
    <section class="panel">
      <div class="panel-h"><h2>האם החלק כבר קיים?</h2><span class="sub">גוררים את קובץ ה-STEP של החלק החדש ומקבלים תשובה תוך שניות</span></div>
      ${isStatic ? `<div class="panel-b"><div class="callout">בגרסה המקוונת אי אפשר להעלות קבצים. למטה מוצגות בדיקות שהורצו בתוכנה על קבצים לדוגמה – לחצו על אחת מהן כדי לראות את התוצאה המלאה.</div></div>` : `
      <div class="panel-b intake">
        <label class="drop" id="drop" tabindex="0" aria-describedby="drop-s">
          <input type="file" id="file" accept=".step,.stp,.STEP,.STP" hidden>
          <span class="drop-mark">${ICON.upload}</span>
          <b id="drop-t">גררו לכאן את קובץ ה-STEP של החלק החדש</b>
          <span class="small muted" id="drop-s">או לחצו לבחירת קובץ STEP (עד 200MB)</span>
        </label>
        <form class="stack" id="fields" autocomplete="off">
          <div class="field"><label for="f-pn">מק"ט מתוכנן <span class="muted small">(לא חובה)</span></label>
            <input id="f-pn" dir="ltr" maxlength="60" placeholder="למשל 200-5120"><span class="help">נבדוק גם שהמספר לא תפוס באף מערכת וב-ERP.</span></div>
          <div class="field"><label for="f-name">שם או תיאור <span class="muted small">(לא חובה)</span></label>
            <input id="f-name" maxlength="200" placeholder='למשל: תושבת מנוע NEMA23'><span class="help">לחלקים תקניים (ברגים, מסבים, שגמים) כדאי לכתוב את המפרט המלא.</span></div>
          <div class="field"><label for="f-mat">חומר <span class="muted small">(לא חובה)</span></label>
            <input id="f-mat" maxlength="80" placeholder="למשל: אלומיניום 6061"></div>
          <button class="btn primary big" id="go" type="submit" disabled>${ICON.inspect}בדוק אם החלק קיים</button>
        </form>
      </div>
      <div class="panel-b run-box" id="run" hidden><div class="progress"><div style="width:4%"></div></div><div class="small" id="run-t"></div></div>`}
      <div class="panel-b intake-foot small muted">${esc(scope)}: אותו קובץ, אותה צורה (גם ביחידות אחרות), צורה כמעט זהה, תמונת מראה, אותו חלק תקני ומק"ט שכבר תפוס.
        הקובץ נשאר במחשב הזה ולא נשלח לשום מערכת.</div>
      ${samples.length ? `<div class="panel-b samples"><span class="small muted">אין קובץ בהישג יד? נסו קובץ לדוגמה:</span>
        ${samples.map((x) => `<button class="btn small" data-sample="${esc(x.key)}" title="${esc(x.expect || "")}">${esc(x.title)}</button>`).join("")}</div>` : ""}
    </section>
    <section class="panel"><div class="panel-h"><h2>${isStatic ? "בדיקות לדוגמה" : "בדיקות אחרונות"}</h2><span class="sub">${rows.length ? `${n0(rows.length)} בדיקות` : ""}</span></div>
      <div id="hist">${history(rows)}</div></section>`;
  el.querySelectorAll("#hist tr[data-id]").forEach((tr) => (tr.onclick = () => go(`#/check/${tr.dataset.id}`)));
  if (isStatic) return null;

  let file = null, alive = true;
  const drop = el.querySelector("#drop"), input = el.querySelector("#file"), btn = el.querySelector("#go");
  const pick = (f) => {
    if (!f) return;
    if (!/\.(step|stp)$/i.test(f.name)) { toast("אפשר לבדוק קובץ STEP בלבד (‎.step או ‎.stp)", true); return; }
    file = f;
    drop.classList.add("has");
    el.querySelector("#drop-t").innerHTML = `<span class="mono ltr">${esc(f.name)}</span>`;
    el.querySelector("#drop-s").textContent = `${kb(f.size)} · לחצו כדי להחליף קובץ`;
    btn.disabled = false;
    if (!el.querySelector("#f-name").value) el.querySelector("#f-name").focus();
  };
  input.onchange = () => pick(input.files[0]);
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => pick(e.dataTransfer.files[0]));

  const follow = async ({ check_id, job_id }) => {
    const run = el.querySelector("#run");
    run.hidden = false;
    btn.disabled = true;
    el.querySelectorAll("[data-sample]").forEach((b) => (b.disabled = true));
    const frac = { index: [0.05, 0.4], geometry: [0.4, 0.7], compare: [0.7, 0.98], done: [1, 1] };
    for (let i = 0; i < 1200 && alive; i++) {
      await new Promise((r) => setTimeout(r, i < 10 ? 250 : 600));
      let j;
      try { j = await get(`/api/jobs/${job_id}`); } catch { continue; }
      const [a, b] = frac[j.stage] || [0.04, 0.04];
      run.querySelector(".progress > div").style.width = `${Math.round(100 * (a + (b - a) * (j.fraction || 0)))}%`;
      run.querySelector("#run-t").textContent = j.detail || "מתחיל…";
      if (j.status !== "running") {
        if (j.status === "error") { toast(j.error || "הבדיקה נכשלה", true); btn.disabled = false; run.hidden = true; return; }
        if (alive) go(`#/check/${check_id}`);
        return;
      }
    }
  };
  el.querySelector("#fields").onsubmit = async (e) => {
    e.preventDefault();
    if (!file) { input.click(); return; }
    btn.disabled = true;
    try {
      await follow(await uploadCheck(file, { pn: el.querySelector("#f-pn").value, name: el.querySelector("#f-name").value,
        material: el.querySelector("#f-mat").value }));
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  };
  el.querySelectorAll("[data-sample]").forEach((b) => (b.onclick = async () => {
    try { await follow(await send("POST", `/api/checks/sample/${encodeURIComponent(b.dataset.sample)}`)); } catch (err) { toast(err.message, true); }
  }));
  return () => { alive = false; };
}

function partCell(p) {
  return `${pnChip(p.pn)} <span>${esc(p.name || "")}</span><div class="small" style="margin-top:3px">${sysBadge(p.source_kind, p.source)} ${statePill(p.state_class, p.state)}</div>`;
}

// measurements the explanation does not already give: the aligned surface distance of a near-identical shape, the
// scale factor of a unit mistake
function matchMetrics(m) {
  const x = m.metrics || {};
  const bits = [];
  if (x.p95_mm != null && m.geo_relation === "near") bits.push(`אחרי יישור: 95% מפני השטח במרחק של עד ${x.p95_mm.toFixed(2)} מ"מ`);
  if (x.scale && Math.abs(x.scale - 1) > 1e-6) bits.push(`יחס גודל ${(x.scale > 1 ? x.scale : 1 / x.scale).toPrecision(4)}`);
  return bits.length ? `<div class="small muted" style="margin-top:3px">${bits.join(" · ")}</div>` : "";
}
// 'AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }' -> 'STEP AP214'
function schemaName(s) {
  const t = String(s || "").toUpperCase();
  if (!t) return "";
  if (/AP242|10303 442/.test(t)) return "STEP AP242";
  if (/AUTOMOTIVE_DESIGN|10303 214/.test(t)) return "STEP AP214";
  if (/CONFIG_CONTROL_DESIGN|10303 203/.test(t)) return "STEP AP203";
  return t.split(/[\s{]/)[0];
}

async function result({ el, param, setTitle, go }) {
  const c = await get(`/api/checks/${encodeURIComponent(param)}`);
  setTitle(c.input?.name || c.file?.name || param, `<a href="#/check">בדיקת חלק חדש</a> / תוצאה`);
  if (c.status === "running") {
    // opened while the check runs: wait for it here, then show the result in place
    el.innerHTML = `<section class="panel"><div class="empty">הבדיקה עדיין רצה…</div></section>`;
    let alive = true, inner = null;
    (async () => {
      for (let i = 0; i < 600 && alive; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const x = await get(`/api/checks/${encodeURIComponent(param)}`).catch(() => null);
        if (alive && x && x.status !== "running") { inner = await result({ el, param, setTitle, go }); return; }
      }
    })();
    return () => { alive = false; if (inner) inner(); };
  }
  const back = `<div class="row"><a class="btn" href="#/check">${ICON.inspect}בדיקה חדשה</a>${isStatic ? "" : `<span style="flex:1"></span><button class="btn ghost small" id="del">${ICON.trash}מחיקת הבדיקה</button>`}</div>`;
  if (c.status === "error") {
    el.innerHTML = `<section class="verdict warn"><div class="v-mark">${ICON.caution}</div><div class="v-body"><h2>לא ניתן היה לבדוק את הקובץ</h2>
      <p>${esc(c.error)}</p></div></section>${back}`;
    wireDelete(el, param, go);
    return null;
  }
  const v = c.verdict, cov = c.coverage, cnt = c.counts || {};
  const use = v.use;
  const same = (cnt.identical || 0) + (cnt.standard_part || 0);
  const geo = c.geometry || {};
  el.innerHTML = `
    <section class="verdict ${v.tone}" aria-live="polite">
      <div class="v-mark">${TONE_ICON[v.tone] || ICON.go}</div>
      <div class="v-body">
        <h2>${esc(v.title)}</h2>
        <p>${esc(v.text)}</p>
        ${use?.pn ? `<div class="row v-use"><span class="small muted">${v.kind === "exists" ? "המק\"ט להשתמש בו" : "החלק הקיים"}</span>
          ${pnChip(use.pn, v.kind === "exists")} <span>${esc(use.name || "")}</span> ${sysBadge(use.source_kind, use.source)}
          ${use.why ? `<span class="small muted">${esc(use.why)}</span>` : ""} ${uidLink(use.uid, "לכרטיס החלק")}</div>` : ""}
        ${c.notes.filter((n) => n.kind !== "coverage").map((n) => `<div class="v-note ${n.tone}">${esc(n.text)}</div>`).join("")}
      </div>
    </section>

    <div class="readout" style="--cells:5">
      <div class="cell"><span class="r-label">הושווה מול</span><span class="r-value">${n0(cov.with_geometry)}</span><span class="r-note">חלקים עם STEP, מתוך ${n0(cov.parts)} בסריקה</span></div>
      <div class="cell ${same ? "bad" : ""}"><span class="r-label">התאמה מלאה</span><span class="r-value">${n0(same)}</span><span class="r-note">אותה צורה או אותו חלק תקני</span></div>
      <div class="cell"><span class="r-label">כמעט זהים</span><span class="r-value">${n0(cnt.near_identical || 0)}</span><span class="r-note">הבדל של עד אחוזים בודדים</span></div>
      <div class="cell"><span class="r-label">שמות דומים</span><span class="r-value">${n0(cnt.name_similar || 0)}</span><span class="r-note">צורה שונה</span></div>
      <div class="cell"><span class="r-label">זמן הבדיקה</span><span class="r-value">${secs(c.timings?.total_s)}</span><span class="r-note">${datetime(c.at)}</span></div>
    </div>

    <section class="panel"><div class="panel-h"><h2 id="c3-t">החלק החדש מול החלק הקיים</h2><span class="spacer"></span><div class="seg" id="mode"></div></div>
      <div class="panel-b stack" id="c3"></div></section>

    <section class="panel"><div class="panel-h"><h2>מה נמצא</h2><span class="sub">${c.n_matches ? `${n0(c.n_matches)} רשומות קשורות – לחיצה על שורה מציגה אותה בתלת-ממד` : ""}</span></div>
      ${c.matches.length ? `<div class="table-wrap"><table class="t" id="mt"><thead><tr><th>ממצא</th><th>חלק קיים</th><th>ERP</th><th>ביטחון</th><th>הסבר</th></tr></thead>
        <tbody>${c.matches.map((m, i) => `<tr class="click" data-i="${i}"><td>${catPill(m.category)}<div class="small muted" style="margin-top:4px">${esc(m.hint_he)}</div></td>
          <td>${partCell(m.part)}</td>
          <td class="small">${m.part.erp ? `מלאי <b class="num">${n0(m.part.erp.stock)}</b>${m.part.erp.status ? `<div class="muted">${esc(m.part.erp.status)}</div>` : ""}` : '<span class="muted">לא ב-ERP</span>'}</td>
          <td>${confBar(m.confidence)}</td><td class="small">${esc(m.reason_he)}${matchMetrics(m)}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="empty">לא נמצאה אף רשומה קשורה – לא לפי צורה, לא לפי שם ולא לפי מק"ט.</div>`}
    </section>

    <section class="panel"><div class="panel-h"><h2>מה נבדק</h2></div><div class="panel-b grid grid-2">
      <dl class="kv">
        <dt>קובץ</dt><dd><span class="mono ltr">${esc(c.file.name)}</span> <span class="small muted">${kb(c.file.size)}</span></dd>
        ${c.input.pn ? `<dt>מק"ט מתוכנן</dt><dd>${pnChip(c.input.pn)}</dd>` : ""}
        ${c.input.name ? `<dt>שם</dt><dd>${esc(c.input.name)}</dd>` : ""}
        ${c.input.material ? `<dt>חומר</dt><dd>${esc(c.input.material)}</dd>` : ""}
        ${c.spec ? `<dt>מפרט תקני שזוהה</dt><dd class="mono">${esc(c.spec)}</dd>` : ""}
        <dt>בתוך הקובץ</dt><dd class="small">${esc([c.file.product, schemaName(c.file.schema), c.file.system].filter(Boolean).join(" · ") || "—")}</dd>
      </dl>
      <dl class="kv">
        ${geo.ok ? `<dt>מידות מעטפת</dt><dd>${dims(geo.bbox)}</dd><dt>נפח</dt><dd>${cm3(geo.volume_mm3)}</dd>
          <dt>מספר פאות</dt><dd class="num">${n0(geo.n_faces)}</dd>` : `<dt>גיאומטריה</dt><dd class="small">${esc(geo.error || "לא נקראה")}</dd>`}
        <dt>הושווה לסריקה</dt><dd>${datetime(c.run_created)}</dd>
        ${c.notes.filter((n) => n.kind === "coverage").map((n) => `<dt>כיסוי</dt><dd class="small">${esc(n.text)}</dd>`).join("")}
      </dl></div></section>
    ${back}`;
  wireDelete(el, param, go);

  // 3D: the new file against the selected record (the one to use, else the first match that has a model)
  const withStep = c.matches.map((m, i) => [m, i]).filter(([m]) => m.part.has_step);
  let current = -1, dispose = null;
  const show = (i) => {
    const m = c.matches[i];
    if (!m || i === current) return;
    if (!m.part.has_step) { toast("לחלק הזה אין קובץ STEP – אין השוואה תלת-ממדית"); return; }
    current = i;
    el.querySelectorAll("#mt tr[data-i]").forEach((tr) => tr.classList.toggle("sel", +tr.dataset.i === i));
    if (dispose) dispose();
    const b = m.uid, run = c.run_id || "latest";
    dispose = compare3d(el.querySelector("#c3"), {
      labelA: `<span class="pill dye plain">החלק החדש</span> <span class="mono small ltr">${esc(c.file.name)}</span>`,
      labelB: `<span class="small muted">קיים</span> ${pnChip(m.part.pn)} ${sysBadge(m.part.source_kind, "")}`,
      overlayLabel: `<span class="pill neutral plain">אפור = החלק החדש</span> <span class="pill brass plain">זהב שקוף = ${esc(m.part.pn || "הקיים")}, מיושר עליו</span>`,
      seg: el.querySelector("#mode"), initial: ["near", "mirror"].includes(m.geo_relation) ? "heat" : "side",
      load: {
        meshA: () => binary(`/api/checks/${encodeURIComponent(param)}/mesh`),
        meshB: () => binary(`/api/mesh/${run}/${encodeURIComponent(b)}`),
        align: () => get(`/api/checks/${encodeURIComponent(param)}/align`, { b }),
        compare: () => binary(`/api/checks/${encodeURIComponent(param)}/compare`, { b }),
      },
    });
  };
  el.querySelectorAll("#mt tr[data-i]").forEach((tr) => (tr.onclick = (e) => { if (!e.target.closest("a")) show(+tr.dataset.i); }));
  const first = withStep.find(([m]) => use && m.uid === use.uid) || withStep[0];
  if (first) show(first[1]);
  else {
    el.querySelector("#mode").hidden = true;
    el.querySelector("#c3-t").textContent = "החלק החדש";
    el.querySelector("#c3").innerHTML = `<div id="solo" class="solo"></div><p class="small muted">${c.matches.length ? "לרשומות שנמצאו אין קובץ STEP, ולכן מוצג רק החלק החדש." : "אין חלק קיים להשוות אליו."}</p>`;
    const { Viewer } = await import("../viewer3d.js");
    const vs = new Viewer(el.querySelector("#solo"), { label: `<span class="pill dye plain">החלק החדש</span> <span class="mono small ltr">${esc(c.file.name)}</span>` });
    vs.loadUrl(`/api/checks/${encodeURIComponent(param)}/mesh`);
    dispose = () => vs.dispose();
  }
  return () => { if (dispose) dispose(); };
}

function wireDelete(el, cid, go) {
  const del = el.querySelector("#del");
  if (!del) return;
  del.onclick = async () => {
    if (!(await confirmInline("למחוק את הבדיקה ואת הקובץ שהועלה? (רק מהתוכנה – שום מערכת לא משתנה)", "מחיקה"))) return;
    try { await send("DELETE", `/api/checks/${encodeURIComponent(cid)}`); toast("הבדיקה נמחקה"); go("#/check"); } catch (e) { toast(e.message, true); }
  };
}

export async function render(ctx) {
  return ctx.param ? result(ctx) : intake(ctx);
}
