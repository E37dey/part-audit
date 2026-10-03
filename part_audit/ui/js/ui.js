// Small UI kit: toasts, modal dialogs, in-page confirmation, decision bar, simple bar charts.
import { esc, DECISION } from "./util.js";
import { send, isStatic } from "./api.js";

export function toast(msg, bad = false) {
  const box = document.getElementById("toasts");
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), bad ? 6500 : 3500);
}

export function modal({ title, body, actions = [], wide = false, onClose = null }) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal" role="dialog" aria-modal="true" style="${wide ? "width:min(1100px,100%)" : ""}">
    <div class="panel-h"><h2>${esc(title)}</h2><span class="spacer"></span><button class="btn ghost small" data-close aria-label="סגור">✕</button></div>
    <div class="panel-b modal-body"></div>
    ${actions.length ? '<div class="modal-foot"></div>' : ""}</div>`;
  const bodyEl = back.querySelector(".modal-body");
  if (typeof body === "string") bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); if (onClose) onClose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest("[data-close]")) close(); });
  const foot = back.querySelector(".modal-foot");
  actions.forEach((a) => {
    const b = document.createElement("button");
    b.className = "btn " + (a.kind || "");
    b.textContent = a.label;
    b.onclick = async () => { if (a.onClick) { const keep = await a.onClick(bodyEl, close); if (keep === true) return; } close(); };
    foot.appendChild(b);
  });
  document.body.appendChild(back);
  const first = back.querySelector("input, select, textarea, button.primary");
  if (first) first.focus();
  return { el: back, body: bodyEl, close };
}

export function confirmInline(text, okLabel = "אישור") {
  return new Promise((resolve) => {
    modal({ title: "אישור פעולה", body: `<p>${esc(text)}</p>`,
      actions: [{ label: okLabel, kind: "primary", onClick: () => resolve(true) }, { label: "ביטול", onClick: () => resolve(false) }],
      onClose: () => resolve(false) });
  });
}

// approve / reject / review bar for a group, pair, mapping row or issue
export function decisionBar(el, { type, id, current = "", note = "", by = "", at = "", masterChoices = null, master = "", onSaved = null,
  labels = {} }) {
  const L = { approve: labels.approve || "אשר", reject: labels.reject || "דחה", review: labels.review || "לבדיקה" };
  const [curHe, tone] = DECISION[current || ""] || DECISION[""];
  el.innerHTML = `<div class="decision">
      <span class="pill ${tone}">${curHe}</span>
      ${by ? `<span class="small muted">${esc(by)} · ${esc((at || "").replace("T", " ").slice(0, 16))}</span>` : ""}
      ${masterChoices ? `<label class="small">מק"ט יעד <select data-master>${masterChoices.map((c) => `<option value="${esc(c.value)}" ${c.value === master ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></label>` : ""}
      <textarea data-note placeholder="הערה (לא חובה) – למשל: נבדק מול שרטוט, להחליף במלאי הקיים">${esc(note || "")}</textarea>
      <button class="btn ok" data-d="approve">${L.approve}</button>
      <button class="btn bad" data-d="reject">${L.reject}</button>
      <button class="btn" data-d="review">${L.review}</button>
    </div>${isStatic ? '<div class="small muted" style="margin-top:6px">בגרסת ההדגמה המקוונת ההחלטות נשמרות רק בלשונית הזו.</div>' : ""}`;
  el.querySelectorAll("[data-d]").forEach((b) => (b.onclick = async () => {
    const body = { target_type: type, target_id: id, decision: b.dataset.d, note: el.querySelector("[data-note]").value };
    const ms = el.querySelector("[data-master]");
    if (ms) body.master_uid = ms.value;
    try {
      await send("POST", "/api/decisions", body);
      toast(b.dataset.d === "approve" ? "ההחלטה נשמרה: אושר" : b.dataset.d === "reject" ? "ההחלטה נשמרה: נדחה" : "סומן לבדיקה");
      if (onSaved) onSaved(b.dataset.d);
    } catch (e) { toast(e.message, true); }
  }));
}

export function bars(rows, { max = null, fmt = (x) => x, alt = false } = {}) {
  const m = max ?? Math.max(1, ...rows.map((r) => r.value));
  return `<div class="bars">${rows.map((r) => `<div class="bar-row"><span title="${esc(r.label)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.html || esc(r.label)}</span>
    <span class="track">${r.parts ? r.parts.map((p) => `<span class="fill ${p.alt ? "alt" : ""}" style="width:${(100 * p.value) / m}%"></span>`).join("")
      : `<span class="fill ${alt ? "alt" : ""}" style="width:${(100 * r.value) / m}%"></span>`}</span>
    <span class="v">${fmt(r.value)}</span></div>`).join("")}</div>`;
}

export function tabs(el, items, onSelect, active) {
  el.innerHTML = items.map((t) => `<button type="button" data-k="${esc(t.key)}" class="${t.key === active ? "on" : ""}">${esc(t.label)}${t.count != null ? `<span class="count">${t.count}</span>` : ""}</button>`).join("");
  el.querySelectorAll("button").forEach((b) => (b.onclick = () => {
    el.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    onSelect(b.dataset.k);
  }));
}
