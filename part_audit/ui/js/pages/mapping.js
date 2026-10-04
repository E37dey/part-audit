// The part-number mapping that results from the approvals: old part number -> the one that stays.
import { get, send, isStatic } from "../api.js";
import { esc, n0, pnChip, decisionPill, confBar, uidLink, debounce, ICON } from "../util.js";
import { toast, confirmInline } from "../ui.js";

const PAGE = 200;

export async function render({ el, setTitle, refreshStatus, state }) {
  setTitle("מיפוי ואישורים", "איזה מק\"ט מוחלף באיזה – אחרי אישור המהנדס");
  const rows = await get("/api/runs/latest/mapping");
  const f = { dec: "pending", q: "", shown: PAGE };
  const sel = new Set();
  const count = (d) => rows.filter((r) => (d === "pending" ? !r.decision : r.decision === d)).length;

  el.innerHTML = `
    <section class="kpis">
      <div class="kpi"><span class="label">שורות מיפוי</span><span class="value">${n0(rows.length)}</span><span class="note">מק"ט קיים ← מק"ט שנשאר</span></div>
      <div class="kpi"><span class="label">אושרו</span><span class="value" style="color:var(--ok)" id="k-ok">${n0(count("approve"))}</span><span class="note">מסומנות "מאושר" בקובץ ה-Excel – לביצוע</span></div>
      <div class="kpi"><span class="label">נדחו</span><span class="value" style="color:var(--bad)" id="k-bad">${n0(count("reject"))}</span><span class="note">מסומנות "נדחה" – לא משנים</span></div>
      <div class="kpi"><span class="label">ממתינים</span><span class="value" id="k-wait">${n0(count("pending"))}</span><span class="note">החלטה על קבוצה חלה על כל השורות שלה</span></div>
    </section>
    <div class="callout small">התוכנה לא משנה שום דבר ב-ERP או ב-PDM. אחרי האישורים מייצאים קובץ Excel, והצוות מבצע את ההחלפות לפי הנהלים שלכם.
      ההחלטה האחרונה קובעת: החלטה על שורה אחרי ההחלטה על הקבוצה היא חריג לשורה הזו, והחלטה חדשה על הקבוצה חלה שוב על כל השורות שלה.</div>
    <div class="panel">
      <div class="panel-h toolbar">
        <input type="search" id="q" placeholder='חיפוש לפי מק"ט או שם' aria-label="חיפוש">
        <div class="seg" id="dec"><button data-v="pending" class="on">ממתינים</button><button data-v="approve">אושרו</button>
          <button data-v="reject">נדחו</button><button data-v="review">לבדיקה</button><button data-v="">הכול</button></div>
        <span style="flex:1"></span>
        <button class="btn primary" id="xls">${ICON.xls}ייצוא Excel לביצוע</button>
      </div>
      <div class="panel-h" id="bulk" hidden style="background:var(--dye-soft)"><b id="bulk-n"></b>
        <button class="btn ok small" data-b="approve">אשר</button><button class="btn bad small" data-b="reject">דחה</button>
        <button class="btn small" data-b="review">לבדיקה</button><button class="btn ghost small" data-b="clear">נקה בחירה</button></div>
      <div class="table-wrap"><table class="t"><thead><tr><th class="sel-col"><input type="checkbox" id="all" aria-label="בחר הכול"></th>
        <th>מק"ט קיים</th><th></th><th>מק"ט שנשאר</th><th>למה</th><th class="n">שימושים</th><th class="n">מלאי</th><th>החלטה</th><th></th></tr></thead>
        <tbody id="tb"></tbody></table></div>
      <div class="panel-b small muted row" id="foot"></div>
    </div>`;

  const filtered = () => {
    const q = f.q.trim().toLowerCase();
    return rows.filter((r) => (f.dec === "" || (f.dec === "pending" ? !r.decision : r.decision === f.dec))
      && (!q || [r.old_pn, r.old_name, r.new_pn, r.new_name].some((x) => (x || "").toLowerCase().includes(q))));
  };
  const draw = () => {
    const r = filtered();
    el.querySelector("#tb").innerHTML = r.slice(0, f.shown).map((m) => `<tr data-id="${m.id}">
      <td class="sel-col"><input type="checkbox" data-sel="${m.id}" ${sel.has(m.id) ? "checked" : ""} aria-label="בחר"></td>
      <td>${uidLink(m.old_uid, pnChip(m.old_pn))}<div class="small">${esc(m.old_name)}</div><div class="small muted">${esc(m.old_source)}</div></td>
      <td class="muted" aria-hidden="true">←</td>
      <td>${uidLink(m.new_uid, pnChip(m.new_pn, true))}<div class="small">${esc(m.new_name)}</div>
        ${m.target_overridden ? '<div class="small muted">היעד שאושר על ידי המאשר</div>' : ""}</td>
      <td class="small" style="min-width:280px" title="${esc(m.reason_he)}">${esc(m.reason_he.split(";")[0])}
        <div class="muted" style="margin-top:3px">${esc(m.why_target_he)} · ביטחון ${confBar(m.confidence)} · <a href="#/group/${m.group_id}">לקבוצה</a></div></td>
      <td class="n">${n0(m.where_used)}</td><td class="n">${n0(m.erp_stock)}</td>
      <td>${decisionPill(m.decision)}${m.inherited ? '<div class="small muted">לפי הקבוצה</div>' : ""}</td>
      <td class="nowrap"><button class="btn small ok" data-one="approve" title="אשר את השורה">✓</button> <button class="btn small bad" data-one="reject" title="דחה את השורה">✕</button></td></tr>`).join("")
      || '<tr><td colspan="9"><div class="empty">אין שורות שמתאימות לסינון</div></td></tr>';
    el.querySelector("#foot").innerHTML = `מוצגות ${n0(Math.min(f.shown, r.length))} מתוך ${n0(r.length)}
      ${r.length > f.shown ? '<button class="btn small" id="more">הצג עוד</button>' : ""}`;
    const more = el.querySelector("#more");
    if (more) more.onclick = () => { f.shown += PAGE; draw(); };
    el.querySelector("#bulk").hidden = !sel.size;
    el.querySelector("#bulk-n").textContent = `${n0(sel.size)} שורות מסומנות`;
    el.querySelector("#k-ok").textContent = n0(count("approve"));
    el.querySelector("#k-bad").textContent = n0(count("reject"));
    el.querySelector("#k-wait").textContent = n0(count("pending"));
  };
  const save = async (ids, decision) => {
    try {
      await send("POST", "/api/decisions", { target_type: "mapping", target_ids: ids, decision });
      rows.forEach((r) => { if (ids.includes(r.id)) { r.decision = decision; r.inherited = false; } });
      toast(ids.length > 1 ? `נשמר עבור ${ids.length} שורות` : "נשמר");
      refreshStatus();
      draw();
    } catch (e) { toast(e.message, true); }
  };
  el.querySelector("#tb").addEventListener("click", (e) => {
    const cb = e.target.closest("[data-sel]");
    if (cb) { cb.checked ? sel.add(cb.dataset.sel) : sel.delete(cb.dataset.sel); draw(); return; }
    const one = e.target.closest("[data-one]");
    if (one) save([one.closest("tr").dataset.id], one.dataset.one);
  });
  el.querySelector("#all").onchange = (e) => { filtered().slice(0, f.shown).forEach((r) => (e.target.checked ? sel.add(r.id) : sel.delete(r.id))); draw(); };
  el.querySelector("#q").oninput = debounce((e) => { f.q = e.target.value; f.shown = PAGE; draw(); }, 150);
  const seg = el.querySelector("#dec");
  seg.querySelectorAll("button").forEach((b) => (b.onclick = () => { seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); f.dec = b.dataset.v; f.shown = PAGE; draw(); }));
  el.querySelectorAll("[data-b]").forEach((b) => (b.onclick = async () => {
    if (b.dataset.b === "clear") { sel.clear(); el.querySelector("#all").checked = false; draw(); return; }
    if (!(await confirmInline(`לשמור "${b.textContent}" עבור ${sel.size} שורות?`, "כן"))) return;
    await save([...sel], b.dataset.b);
    sel.clear(); el.querySelector("#all").checked = false; draw();
  }));
  el.querySelector("#xls").onclick = () => {
    if (isStatic) { toast("ייצוא Excel זמין באפליקציה המקומית"); return; }
    location.href = `/api/runs/${state.status.latest_run}/export.xlsx`;
  };
  draw();
}
