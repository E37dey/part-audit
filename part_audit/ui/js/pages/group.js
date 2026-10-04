// One duplicate group: the parts side by side in 3D, their attributes, the impact of merging, the evidence and the decision.
import { get } from "../api.js";
import { esc, n0, money, datetime, sysBadge, pnChip, groupPill, catPill, confBar, uidLink, DECISION, ICON } from "../util.js";
import { decisionBar } from "../ui.js";
import { Viewer, linkViewers } from "../viewer3d.js";
import { attrTable } from "../compare.js";

const MAX_VIEWERS = 6;

export async function render({ el, param, setTitle, refreshStatus }) {
  const [g, list] = await Promise.all([get(`/api/runs/latest/groups/${encodeURIComponent(param)}`), get("/api/runs/latest/groups")]);
  const cur = g.currency || "ILS";
  // review order = the list's default order (most stock on duplicate part numbers first)
  const order = [...list].sort((x, y) => (y.redundant_stock_value || 0) - (x.redundant_stock_value || 0));
  const at = order.findIndex((x) => x.id === g.id);
  const prev = at > 0 ? order[at - 1] : null, next = at >= 0 && at < order.length - 1 ? order[at + 1] : null;
  const nextPending = () => { for (let k = 1; k < order.length; k++) { const x = order[(at + k) % order.length]; if (!x.decision && x.id !== g.id) return x; } return null; };
  const master = g.decision_master || g.master_uid;
  // proposed part first, then by system (plain code-point order, the same order the static export uses)
  const parts = [...g.parts].sort((a, b) => (a.uid === g.master_uid ? -1 : b.uid === g.master_uid ? 1 : (a.source > b.source) - (a.source < b.source)));
  const byUid = Object.fromEntries(parts.map((p) => [p.uid, p]));
  const withStep = parts.filter((p) => p.has_step);
  setTitle(g.name || "קבוצת כפילות", `<a href="#/groups">כפילויות</a> / ${esc(g.spec || g.master_pn || g.id)}`);

  el.innerHTML = `
    <section class="panel"><div class="panel-b stack" style="gap:12px">
      <div class="row">${groupPill(g.category)}${g.cross_source ? '<span class="pill info">חוצה מערכות</span>' : ""}
        <span class="small muted">${n0(parts.length)} רשומות · ${n0(g.pns.length)} מק"טים · ציון ביטחון ${confBar(g.confidence)}</span>
        <span class="spacer" style="flex:1"></span><span id="dec-pill"></span>
        <span class="pager">${prev ? `<a class="btn small ghost" href="#/group/${prev.id}" title="הקבוצה הקודמת ברשימה">${ICON.prev}הקודמת</a>` : ""}
          <span class="small muted num">${at + 1} מתוך ${order.length}</span>
          ${next ? `<a class="btn small ghost" href="#/group/${next.id}" title="הקבוצה הבאה ברשימה">הבאה${ICON.next}</a>` : ""}</span></div>
      <p><b>למה זה אותו חלק:</b> ${esc(g.reason_he || "—")}</p>
      <p><b>המק"ט המוצע להישאר:</b> ${pnChip(g.master_pn, true)} <span class="muted">(${esc(g.master_reason_he)})</span><span id="chosen"></span></p>
      <div class="row small">${g.pns.map((p) => pnChip(p, p === g.master_pn)).join(" ")}</div>
    </div></section>

    <section class="panel"><div class="panel-h"><h2>המודלים זה לצד זה</h2><span class="sub">גוררים כדי לסובב – כל התצוגות זזות יחד</span></div>
      <div class="panel-b">
        ${withStep.length ? `<div class="viewers" id="viewers">${withStep.slice(0, MAX_VIEWERS).map((p, i) => `<div data-v="${i}"></div>`).join("")}</div>` : '<div class="empty">לאף אחת מהרשומות אין קובץ STEP – ההשוואה מבוססת על המפרט והשמות.</div>'}
        ${withStep.length > MAX_VIEWERS ? `<p class="small muted" style="margin-top:8px">מוצגים ${MAX_VIEWERS} מתוך ${withStep.length} מודלים.</p>` : ""}
        ${parts.length > withStep.length ? `<p class="small muted" style="margin-top:8px">בלי קובץ STEP: ${parts.filter((p) => !p.has_step).map((p) => pnChip(p.pn) + " " + sysBadge(p.source_kind, "")).join(" · ")}</p>` : ""}
      </div></section>

    <section class="panel"><div class="panel-h"><h2>החלטה</h2><span class="sub">אישור מסמן את המק"טים האחרים להחלפה במק"ט היעד. שום דבר לא נכתב למערכות – הביצוע לפי קובץ ה-Excel.</span></div>
      <div class="panel-b stack"><div id="decision"></div><div class="row" id="after"></div><div id="history"></div></div></section>

    <section class="panel"><div class="panel-h"><h2>השוואת נתונים</h2><span class="sub">העמודה הראשונה היא המק"ט המוצע</span></div>
      <div class="panel-b">${attrTable(parts, (p) => `${pnChip(p.pn, p.uid === g.master_uid)}<div style="margin-top:4px">${sysBadge(p.source_kind, "")} ${uidLink(p.uid, "לכרטיס החלק")}</div>`, { masterUid: g.master_uid })}</div></section>

    <section class="grid grid-2">
      <div class="panel"><div class="panel-h"><h2>מה ישתנה אם מאחדים</h2></div>
        <div class="panel-b stack">
          <div class="readout mini" style="--cells:3">
            <div class="cell"><span class="r-label">מק"טים שיבוטלו</span><span class="r-value" id="k-red"></span></div>
            <div class="cell"><span class="r-label">שורות עץ מוצר לעדכון</span><span class="r-value" id="k-bom"></span></div>
            <div class="cell"><span class="r-label">מלאי במק"טים הכפולים</span><span class="r-value" id="k-val"></span></div>
          </div>
          ${g.products?.length ? `<div><b class="small">מוצרים שמשתמשים בחלק:</b> ${g.products.map((x) => `<span class="chip">${esc(x)}</span>`).join(" ")}</div>` : ""}
        </div>
        <div class="table-wrap"><table class="t"><thead><tr><th>ERP</th><th>תיאור</th><th class="n">מלאי</th><th class="n">עלות</th><th class="n">שווי</th><th>סטטוס</th></tr></thead><tbody>
          ${g.erp.length ? g.erp.map((r) => `<tr><td>${pnChip(r.pn, r.is_master)}</td><td>${esc(r.description)}</td><td class="n">${n0(r.stock)}</td>
            <td class="n">${money(r.unit_cost, cur)}</td><td class="n">${money(r.value, cur)}</td><td>${esc(r.status || "")}</td></tr>`).join("")
            : '<tr><td colspan="6" class="muted">אף אחד מהמק"טים לא נמצא ב-ERP</td></tr>'}
        </tbody></table></div></div>
      <div class="panel"><div class="panel-h"><h2>איפה החלקים בשימוש</h2><span class="sub">${n0(g.where_used.length)} שורות בעצי מוצר</span></div>
        <div class="table-wrap" style="max-height:420px"><table class="t"><thead><tr><th>מכלול</th><th>מערכת</th><th class="n">כמות</th><th>דרך מק"ט</th></tr></thead><tbody>
          ${g.where_used.length ? g.where_used.map((u) => `<tr><td>${u.uid ? uidLink(u.uid, pnChip(u.pn)) : pnChip(u.pn)} <span class="small">${esc(u.name || "")}</span></td>
            <td>${u.source === "ERP" ? sysBadge("ERP", "ERP") : esc(u.source)}</td><td class="n">${n0(u.qty)}</td>
            <td>${pnChip(u.via, u.via === g.master_pn)}</td></tr>`).join("")
            : '<tr><td colspan="4" class="muted">לא נמצאו שימושים בעצי מוצר</td></tr>'}
        </tbody></table></div></div>
    </section>

    <section class="panel"><div class="panel-h"><h2>הראיות</h2><span class="sub">ההשוואות בין הרשומות בקבוצה</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>רשומה א</th><th>רשומה ב</th><th>סוג</th><th>פירוט</th><th class="n">ביטחון</th><th></th></tr></thead><tbody>
        ${g.pairs.map((p) => `<tr><td>${pnChip(byUid[p.a]?.pn)} ${sysBadge(byUid[p.a]?.source_kind, "")}</td><td>${pnChip(byUid[p.b]?.pn)} ${sysBadge(byUid[p.b]?.source_kind, "")}</td>
          <td>${catPill(p.category)}</td><td class="small">${esc(p.reason_he)}</td><td class="n">${confBar(p.confidence)}</td>
          <td>${byUid[p.a]?.has_step && byUid[p.b]?.has_step ? `<a href="#/pair/${p.id}" class="small nowrap">השוואה בתלת-ממד</a>` : ""}</td></tr>`).join("")}
      </tbody></table></div></section>`;

  // decision + history (re-rendered after saving without reloading the 3D views)
  const paint = (d, saved = false) => {
    const [he, tone] = DECISION[d.decision || ""] || DECISION[""];
    el.querySelector("#dec-pill").innerHTML = `<span class="pill ${tone}">${he}</span>`;
    // an approved target replaces the proposal; a target picked with "review" is shown but changes nothing yet
    const picked = d.decision_master && d.decision_master !== g.master_uid ? byUid[d.decision_master] : null;
    el.querySelector("#chosen").innerHTML = d.final_master_pn && d.final_master_pn !== g.master_pn
      ? ` · <b>אושר כיעד:</b> ${pnChip(d.final_master_pn, true)}`
      : picked && d.decision === "review" ? ` · <b>נבחר לבדיקה:</b> ${pnChip(picked.pn)}` : "";
    // the impact follows the part number that stays
    el.querySelector("#k-red").textContent = n0(d.redundant_pns);
    el.querySelector("#k-bom").textContent = n0(d.bom_lines_to_update);
    el.querySelector("#k-val").textContent = money(d.redundant_stock_value, cur);
    decisionBar(el.querySelector("#decision"), {
      type: "group", id: g.id, current: d.decision, note: d.decision_note, by: d.decision_by, at: d.decision_at,
      masterChoices: parts.filter((p) => p.pn).map((p) => ({ value: p.uid, label: `${p.pn} · ${p.source}` })),
      master: d.decision_master || master, labels: { approve: "אשר איחוד", reject: "לא אותו חלק", review: "לבדיקה" },
      onSaved: async () => {
        const fresh = await get(`/api/runs/latest/groups/${encodeURIComponent(g.id)}`);
        paint(fresh, true); refreshStatus();
      },
    });
    // the way on: after a decision, the next group that still waits
    const np = nextPending();
    el.querySelector("#after").innerHTML = np ? `<a class="btn ${saved ? "primary" : "ghost"}" id="go-next" href="#/group/${np.id}">לקבוצה הבאה שממתינה${ICON.next}</a>
      <span class="small muted">${esc(np.name || np.master_pn || "")}</span>` : (saved ? '<span class="small muted">אין עוד קבוצות שממתינות להחלטה.</span>' : "");
    if (saved) el.querySelector("#go-next")?.focus();
    el.querySelector("#history").innerHTML = d.history?.length ? `<details><summary class="small">היסטוריית החלטות (${d.history.length})</summary>
      <table class="t" style="margin-top:8px"><thead><tr><th>מתי</th><th>מי</th><th>החלטה</th><th>מק"ט יעד</th><th>הערה</th></tr></thead><tbody>
      ${d.history.map((h) => `<tr><td class="nowrap">${datetime(h.created)}</td><td>${esc(h.user)}</td><td>${(DECISION[h.decision] || [h.decision])[0]}</td>
        <td>${h.master_uid ? pnChip(byUid[h.master_uid]?.pn || h.master_uid) : "—"}</td><td>${esc(h.note || "")}</td></tr>`).join("")}</tbody></table></details>` : "";
  };
  paint(g);

  // 3D views
  const viewers = [];
  const shown = withStep.slice(0, MAX_VIEWERS);
  shown.forEach((p, i) => {
    const box = el.querySelector(`[data-v="${i}"]`);
    const v = new Viewer(box, { label: `${pnChip(p.pn, p.uid === g.master_uid)} ${sysBadge(p.source_kind, "")}` });
    viewers.push(v);
    // every model is turned to the orientation of the first one, so the same view shows the same side
    v.loadUrl(`/api/mesh/latest/${encodeURIComponent(p.uid)}`).then((o) => {
      if (!o || i === 0) return;
      get("/api/align/latest", { a: shown[0].uid, b: p.uid }).then((al) => v.orient(al.matrix)).catch(() => {});
    });
  });
  linkViewers(viewers);
  return () => viewers.forEach((v) => v.dispose());
}
