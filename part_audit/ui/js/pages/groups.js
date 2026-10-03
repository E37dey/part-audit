// All duplicate groups: filter, sort, open one, or approve several at once.
import { get, send } from "../api.js";
import { esc, n0, money, pnChip, sysBadge, groupPill, decisionPill, confBar, debounce } from "../util.js";
import { toast, confirmInline } from "../ui.js";

const PAGE = 150;

export async function render({ el, setTitle, refreshStatus, state }) {
  setTitle("כפילויות", "אותו חלק תחת כמה מק\"טים – לפי גיאומטריה ולפי מפרט תקני");
  const [rows, summary] = await Promise.all([get("/api/runs/latest/groups"), get("/api/runs/latest/summary")]);
  const kindOf = Object.fromEntries(summary.sources.map((x) => [x.name, x.kind]));
  const f = { q: "", cat: "", dec: "pending", cross: false, sort: "value", shown: PAGE };
  const sel = new Set();

  el.innerHTML = `
    <div class="callout small">כל קבוצה היא חלק אחד שקיים בכמה רשומות. התוכנה מציעה איזה מק"ט יישאר (קיים ב-ERP, משוחרר, בשימוש, עם מלאי)
      ומהנדס מאשר או דוחה. בקובץ ה-Excel כל שורה מסומנת לפי ההחלטה (מאושר, נדחה או ממתין), <b>ורק שורות מאושרות הן לביצוע.</b></div>
    <div class="panel">
      <div class="panel-h toolbar">
        <input type="search" id="q" placeholder='חיפוש לפי שם, מק"ט או מפרט (למשל M8x20)' aria-label="חיפוש">
        <div class="seg" id="cat"><button data-v="" class="on">הכול</button><button data-v="standard">חלקים תקניים</button><button data-v="geometry">גיאומטריה זהה</button></div>
        <div class="seg" id="dec"><button data-v="pending" class="on">ממתינים</button><button data-v="approve">אושרו</button><button data-v="reject">נדחו</button><button data-v="review">לבדיקה</button><button data-v="">הכול</button></div>
        <label class="check small"><input type="checkbox" id="cross"> רק חוצות מערכות</label>
        <span class="spacer" style="flex:1"></span>
        <label class="small">מיון <select id="sort"><option value="value">שווי מלאי כפול</option><option value="members">מספר רשומות</option>
          <option value="used">שימושים</option><option value="conf">ביטחון</option><option value="name">שם</option></select></label>
      </div>
      <div class="panel-h" id="bulk" hidden style="background:var(--dye-soft)">
        <b id="bulk-n"></b><button class="btn ok small" data-b="approve">אשר את המסומנות</button>
        <button class="btn bad small" data-b="reject">דחה את המסומנות</button><button class="btn small" data-b="review">סמן לבדיקה</button>
        <button class="btn ghost small" data-b="clear">נקה בחירה</button>
        <span class="small muted">באישור מרוכז כל קבוצה מאושרת עם מק"ט היעד שלה: זה שנבחר בה קודם, או המוצע.</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th class="sel-col"><input type="checkbox" id="all" aria-label="בחר הכול"></th>
        <th>חלק</th><th>סוג</th><th>מק"ט שנשאר</th><th>מק"טים כפולים</th><th>מערכות</th><th class="n">שימושים</th>
        <th class="n">מלאי במק"טים הכפולים</th><th class="n">ביטחון</th><th>החלטה</th></tr></thead><tbody id="tb"></tbody></table></div>
      <div class="panel-b small muted row" id="foot"></div>
    </div>`;

  const tb = el.querySelector("#tb");
  const filtered = () => {
    const q = f.q.trim().toLowerCase();
    let r = rows.filter((g) => (!f.cat || g.category === f.cat) && (!f.cross || g.cross_source)
      && (f.dec === "" || (f.dec === "pending" ? !g.decision : g.decision === f.dec))
      && (!q || [g.name, g.spec, ...g.pns].some((x) => (x || "").toLowerCase().includes(q))));
    const key = { value: (g) => -(g.redundant_stock_value || 0), members: (g) => -g.n_members, used: (g) => -g.n_used,
      conf: (g) => -(g.confidence || 0), name: (g) => g.name || "" }[f.sort];
    return r.sort((a, b) => { const x = key(a), y = key(b); return typeof x === "string" ? x.localeCompare(y, "he") : x - y; });
  };
  const draw = () => {
    const r = filtered();
    tb.innerHTML = r.slice(0, f.shown).map((g) => `<tr class="click" data-id="${g.id}">
      <td class="sel-col"><input type="checkbox" data-sel="${g.id}" ${sel.has(g.id) ? "checked" : ""} aria-label="בחר"></td>
      <td>${esc(g.name)}${g.spec ? `<div class="small muted mono">${esc(g.spec)}</div>` : ""}</td><td>${groupPill(g.category)}</td>
      <td class="nowrap">${pnChip(g.final_master_pn || g.master_pn, true)}${(g.final_master_pn || g.master_pn) !== g.master_pn ? '<div class="small muted">נבחר על ידי המאשר</div>' : ""}</td>
      <td>${g.pns.filter((p) => p !== (g.final_master_pn || g.master_pn)).map((p) => pnChip(p)).join(" ")}</td>
      <td class="nowrap">${g.sources.map((x) => sysBadge(kindOf[x], "")).join("")}</td><td class="n">${n0(g.n_used)}</td>
      <td class="n">${money(g.redundant_stock_value)}</td><td class="n">${confBar(g.confidence)}</td><td>${decisionPill(g.decision)}</td></tr>`).join("")
      || `<tr><td colspan="10"><div class="empty">${rows.length ? "אין קבוצות שמתאימות לסינון" : "לא נמצאו כפילויות בסריקה"}</div></td></tr>`;
    el.querySelector("#foot").innerHTML = `מוצגות ${n0(Math.min(f.shown, r.length))} מתוך ${n0(r.length)} קבוצות (${n0(rows.length)} בסך הכול)
      ${r.length > f.shown ? '<button class="btn small" id="more">הצג עוד</button>' : ""}`;
    const more = el.querySelector("#more");
    if (more) more.onclick = () => { f.shown += PAGE; draw(); };
    bulkBar();
  };
  const bulkBar = () => {
    el.querySelector("#bulk").hidden = !sel.size;
    el.querySelector("#bulk-n").textContent = `${n0(sel.size)} קבוצות מסומנות`;
  };
  tb.addEventListener("click", (e) => {
    const cb = e.target.closest("[data-sel]");
    if (cb) { cb.checked ? sel.add(cb.dataset.sel) : sel.delete(cb.dataset.sel); bulkBar(); return; }
    if (e.target.closest(".sel-col")) return;
    const tr = e.target.closest("tr[data-id]");
    if (tr) location.hash = `#/group/${tr.dataset.id}`;
  });
  el.querySelector("#all").onchange = (e) => {
    filtered().slice(0, f.shown).forEach((g) => (e.target.checked ? sel.add(g.id) : sel.delete(g.id)));
    draw();
  };
  el.querySelector("#q").oninput = debounce((e) => { f.q = e.target.value; f.shown = PAGE; draw(); }, 150);
  segs(el.querySelector("#cat"), (v) => { f.cat = v; draw(); });
  segs(el.querySelector("#dec"), (v) => { f.dec = v; draw(); });
  el.querySelector("#cross").onchange = (e) => { f.cross = e.target.checked; draw(); };
  el.querySelector("#sort").onchange = (e) => { f.sort = e.target.value; draw(); };
  el.querySelectorAll("[data-b]").forEach((b) => (b.onclick = async () => {
    if (b.dataset.b === "clear") { sel.clear(); el.querySelector("#all").checked = false; draw(); return; }
    const he = { approve: "לאשר", reject: "לדחות", review: "לסמן לבדיקה" }[b.dataset.b];
    if (!(await confirmInline(`${he} ${sel.size} קבוצות?`, "כן"))) return;
    try {
      await send("POST", "/api/decisions", { target_type: "group", target_ids: [...sel], decision: b.dataset.b, note: "החלטה מרוכזת" });
      rows.forEach((g) => { if (sel.has(g.id)) g.decision = b.dataset.b; });
      toast(`נשמר עבור ${sel.size} קבוצות`);
      sel.clear(); el.querySelector("#all").checked = false; draw(); refreshStatus();
    } catch (e) { toast(e.message, true); }
  }));
  draw();
}

export function segs(box, onChange) {
  box.querySelectorAll("button").forEach((b) => (b.onclick = () => {
    box.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    onChange(b.dataset.v);
  }));
}
