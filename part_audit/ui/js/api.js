// REST client. In the published demo (window.PA_STATIC) the same calls read pre-exported files and
// decisions are kept in this browser tab only.
const STATIC = !!window.PA_STATIC;
const memDecisions = [];
const staticCache = {};

function staticFile(file, kind = "json") {
  const key = `${kind}:${file}`;
  if (!staticCache[key]) {
    staticCache[key] = fetch(`data/${file}`).then(async (r) => {
      if (!r.ok) throw new Error("הנתון לא נכלל בגרסת ההדגמה המקוונת");
      if (kind === "json") return r.json();
      // 3D packs are base64 text (the hosting serves web file types only)
      const bin = atob((await r.text()).trim());
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      return bytes.buffer;
    });
  }
  return staticCache[key];
}
const staticJson = (file) => staticFile(file);

// decisions made in this tab, oldest first; seq is their exact order (two clicks can share a timestamp)
const latestDecision = (kind, id) => [...memDecisions].reverse().find((x) => x.target_type === kind && x.target_id === id);
const historyOf = (kind, id) => memDecisions.filter((x) => x.target_type === kind && x.target_id === id).reverse()
  .map((d) => ({ ...d, master_uid: d.master_uid || "" }));

// the same rules as the app (names.pn_key, decisions.py): pn keys keep letters and number borders
function pnKey(pn) {
  const toks = String(pn || "").normalize("NFKC").toUpperCase().match(/[A-Zא-ת]+|\d+/g) || [];
  let out = "", afterDigits = false;
  for (const t of toks) {
    if (/^\d+$/.test(t)) { out += (afterDigits ? "." : "") + (t.replace(/^0+/, "") || "0"); afterDigits = true; }
    else { out += t; afterDigits = false; }
  }
  return out;
}
// the most common currency; a tie goes to alphabetical order (decisions.main_currency)
function mainCurrency(curs) {
  if (!curs.length) return null;
  const n = (c) => curs.filter((x) => x === c).length;
  return [...new Set(curs)].sort((a, b) => n(b) - n(a) || (a < b ? -1 : a > b ? 1 : 0))[0];
}
// a where-used line must change unless it names the target: a PDM/PLM line by part number, an ERP line by the
// ERP item the target is linked to (decisions.needs_update)
function needsUpdate(u, targetPn, targetErpPn) {
  if (u.erp_pn) { const t = pnKey(targetErpPn || targetPn); return !!t && pnKey(u.erp_pn) !== t; }
  const t = pnKey(targetPn);
  return !!t && !!u.via && pnKey(u.via) !== t;
}
// what merging into the target changes; targetErpPn is the ERP item the target is linked to (decisions.group_impact)
function groupImpact(g, targetPn, targetErpPn) {
  const keep = pnKey(targetErpPn || targetPn);
  const main = mainCurrency(g.erp.map((e) => e.currency).filter(Boolean));
  const value = g.erp.filter((e) => pnKey(e.pn) !== keep && (!main || !e.currency || e.currency === main)).reduce((t, e) => t + (e.value || 0), 0);
  return { redundant_stock_value: Math.round(value * 100) / 100,
    bom_lines_to_update: g.where_used.filter((u) => needsUpdate(u, targetPn, targetErpPn)).length };
}
// the member whose part number stays: the approved choice, else the proposal (decisions.chosen_target)
function chosenTarget(g, d) {
  const t = d && d.decision === "approve" && d.master_uid && g.parts.find((x) => x.uid === d.master_uid);
  return t && t.pn ? t : g.parts.find((x) => x.uid === g.master_uid);
}
function impactFor(g, t) {
  return groupImpact(g, t.pn, t.erp ? t.erp.pn : null);
}

async function applyDecisions(rows, kind) {
  if (!STATIC || !Array.isArray(rows)) return rows;
  const details = kind === "group" ? await staticJson("group_details.json") : null;
  const out = [];
  for (const r of rows) {
    const d = latestDecision(kind, r.id);
    if (!d) { out.push(r); continue; }
    const row = { ...r, decision: d.decision, decision_note: d.note, decision_by: d.user, decision_at: d.created,
      decision_master: d.master_uid || "" };
    const g = kind === "group" ? details[r.id] : null;
    if (g) {
      const t = chosenTarget(g, d);
      row.final_master_pn = t.uid !== g.master_uid ? t.pn : r.master_pn;
      if (t.uid !== g.master_uid) Object.assign(row, impactFor(g, t));
    }
    out.push(row);
  }
  return out;
}

// the same rule as decisions.effective_mapping: a group approval may name another target part number
async function effectiveMapping(rows) {
  const details = await staticJson("group_details.json");
  const overridden = new Set();
  const extra = [];
  for (const [gid, g] of Object.entries(details)) {
    const d = latestDecision("group", gid);
    const t = chosenTarget(g, d);
    if (!t || t.uid === g.master_uid) continue;
    overridden.add(gid);
    const seen = new Set([pnKey(t.pn)]);
    for (const r of g.parts) {
      if (!r.pn || seen.has(pnKey(r.pn))) continue;
      seen.add(pnKey(r.pn));
      const pair = g.pairs.find((x) => (x.a === r.uid && x.b === t.uid) || (x.b === r.uid && x.a === t.uid));
      extra.push({ id: `M~${gid}~${r.pn}~${t.pn}`, group_id: gid, old_pn: r.pn, old_uid: r.uid, old_name: r.name,
        old_source: r.source, new_pn: t.pn, new_uid: t.uid, new_name: t.name, reason_he: pair ? pair.reason_he : g.reason_he,
        why_target_he: `היעד שאושר על ידי ${d.user}`, confidence: pair ? pair.confidence : g.confidence,
        where_used: g.where_used.filter((x) => x.via === r.pn).length, erp_stock: r.erp ? r.erp.stock : null,
        status: "ממתין לאישור", target_overridden: true });
    }
  }
  return rows.filter((r) => !overridden.has(r.group_id)).concat(extra);
}

async function staticGet(path, params = {}) {
  const p = path.replace(/^\/api\//, "");
  let m;
  if (p === "status") return staticJson("status.json");
  if (p === "connectors") return staticJson("connectors.json");
  if (p === "sources") return staticJson("sources.json");
  if (p === "settings") return (await staticJson("status.json")).settings;
  if (p === "runs") return staticJson("runs.json");
  if (p === "decisions") return [...memDecisions].reverse();
  if ((m = p.match(/^sources\/([^/]+)\/discovery$/))) {
    const x = (await staticJson("discovery.json"))[decodeURIComponent(m[1])];
    if (!x) throw new Error("גילוי שדות לא נכלל בגרסת ההדגמה המקוונת למקור הזה");
    return x;
  }
  if ((m = p.match(/^runs\/[^/]+\/summary$/))) {
    const s = await staticJson("summary.json");
    // the ten groups with the most stock on duplicate part numbers, after the decisions made in this tab
    const top = (await applyDecisions(Object.values(await staticJson("group_details.json")), "group"))
      .sort((a, b) => (b.redundant_stock_value || 0) - (a.redundant_stock_value || 0) || b.members.length - a.members.length).slice(0, 10);
    const decided = new Set(memDecisions.filter((d) => d.target_type === "group").map((d) => d.target_id));
    const approved = new Set(memDecisions.filter((d) => d.target_type === "group" && latestDecision("group", d.target_id)?.decision === "approve").map((d) => d.target_id));
    // money and BOM lines follow the targets approved in this tab
    const summary = { ...s.summary };
    const details = await staticJson("group_details.json");
    for (const id of decided) {
      const g = details[id];
      const t = g && chosenTarget(g, latestDecision("group", id));
      if (!t || t.uid === g.master_uid) continue;
      const imp = impactFor(g, t);
      if ((g.currency || summary.currency) === summary.currency) summary.redundant_stock_value += imp.redundant_stock_value - g.redundant_stock_value;
      summary.bom_lines_to_update += imp.bom_lines_to_update - g.bom_lines_to_update;
    }
    summary.redundant_stock_value = Math.round(summary.redundant_stock_value * 100) / 100;
    return { ...s, summary, top_groups: top, decisions: { pending_groups: Math.max(0, s.decisions.pending_groups - decided.size),
      approved_groups: s.decisions.approved_groups + approved.size } };
  }
  if ((m = p.match(/^runs\/[^/]+\/groups$/))) return applyDecisions(await staticJson("groups.json"), "group");
  if ((m = p.match(/^runs\/[^/]+\/groups\/(.+)$/))) {
    const id = decodeURIComponent(m[1]);
    const g = (await staticJson("group_details.json"))[id];
    if (!g) throw new Error("הקבוצה לא נמצאה");
    return { ...(await applyDecisions([g], "group"))[0], history: historyOf("group", id) };
  }
  if ((m = p.match(/^runs\/[^/]+\/pairs$/))) {
    const rows = await staticJson("pairs.json");
    const cats = params.category ? new Set(params.category.split(",")) : null;
    return applyDecisions(cats ? rows.filter((r) => cats.has(r.category)) : rows, "pair");
  }
  if ((m = p.match(/^runs\/[^/]+\/pairs\/(.+)$/))) {
    const id = decodeURIComponent(m[1]);
    const x = (await staticJson("pair_details.json"))[id];
    if (!x) throw new Error("הזוג לא נמצא");
    return { ...(await applyDecisions([x], "pair"))[0], history: historyOf("pair", id) };
  }
  if ((m = p.match(/^runs\/[^/]+\/findings\/(\w+)$/))) return applyDecisions(await staticJson(`findings_${m[1]}.json`), "issue");
  if ((m = p.match(/^runs\/[^/]+\/mapping$/))) {
    // the row's own decision or its group's, whichever was made last
    return (await effectiveMapping(await staticJson("mapping.json"))).map((r) => {
      const own = latestDecision("mapping", r.id), grp = latestDecision("group", r.group_id);
      const pick = grp && (!own || grp.seq > own.seq) ? grp : own;
      if (!pick) return { ...r, decision: "", inherited: false };
      return { ...r, decision: pick.decision, decision_by: pick.user, decision_at: pick.created, decision_note: pick.note,
        inherited: pick === grp };
    });
  }
  if ((m = p.match(/^runs\/[^/]+\/parts$/))) {
    let rows = await staticJson("parts.json");
    const q = (params.q || "").toLowerCase();
    if (q) rows = rows.filter((x) => [x.pn, x.name, x.native_file, x.description].some((v) => (v || "").toLowerCase().includes(q)));
    if (params.source) rows = rows.filter((x) => x.source === params.source);
    if (params.kind) rows = rows.filter((x) => x.kind === params.kind);
    if (params.flag === "group") rows = rows.filter((x) => x.group_id);
    if (params.flag === "near") rows = rows.filter((x) => x.near_count);
    if (params.flag === "issues") rows = rows.filter((x) => x.issues);
    if (params.flag === "nostep") rows = rows.filter((x) => x.kind === "part" && !x.has_step);
    const off = +params.offset || 0, lim = +params.limit || 200;
    return { total: rows.length, rows: rows.slice(off, off + lim) };
  }
  if ((m = p.match(/^runs\/[^/]+\/parts\/(.+)$/))) {
    const x = (await staticJson("part_details.json"))[decodeURIComponent(m[1])];
    if (!x) throw new Error("החלק לא נמצא");
    return x;
  }
  if ((m = p.match(/^align\/[^/]+$/))) {
    const x = (await staticJson("align.json"))[`${params.a}|${params.b}`];
    if (!x) throw new Error("לא נכלל בגרסת ההדגמה המקוונת");
    return x;
  }
  throw new Error("לא זמין בגרסת ההדגמה המקוונת");
}

// 3D files of the online demo live in a few pack files: index key -> [pack file, offset, length]
async function packed(indexFile, key, missing) {
  const hit = (await staticJson(indexFile))[key];
  if (!hit) throw new Error(missing);
  const buf = await staticFile(hit[0], "bin");
  return buf.slice(hit[1], hit[1] + hit[2]);
}

export async function get(path, params = {}) {
  if (STATIC) return staticGet(path, params);
  const url = new URL(path, location.origin);
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && url.searchParams.set(k, v));
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `שגיאה ${r.status}`);
  return r.json();
}

export async function send(method, path, body) {
  if (STATIC) {
    if (path === "/api/decisions") {
      const ids = body.target_ids || [body.target_id];
      const now = new Date().toISOString();
      const details = body.target_type === "group" ? await staticJson("group_details.json") : {};
      ids.forEach((id) => {
        // like the app: a group decision always records its target - the one chosen now, else the one in effect
        // (approved before, else the proposal), so a bulk decision acts on what the list shows
        const master = body.target_type === "group"
          ? body.master_uid || (details[id] ? chosenTarget(details[id], latestDecision("group", id))?.uid : "") || "" : "";
        memDecisions.push({ ...body, target_id: id, master_uid: master, created: now, user: body.user || "צופה בהדגמה",
          seq: memDecisions.length + 1 });
      });
      return { ok: true, saved: ids.length };
    }
    throw new Error("בגרסת ההדגמה המקוונת אין חיבור למערכות – הפעולה זמינה באפליקציה המקומית");
  }
  const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `שגיאה ${r.status}`);
  return r.json();
}

export async function binary(path, params = {}) {
  if (STATIC) {
    let m;
    if ((m = path.match(/^\/api\/mesh\/[^/]+\/(.+)$/))) return packed("mesh_index.json", decodeURIComponent(m[1]), "אין תצוגה תלת-ממדית לחלק הזה בגרסה המקוונת");
    if (path.startsWith("/api/compare/")) return packed("compare_index.json", `${params.a}|${params.b}`, "מפת הסטיות לזוג הזה לא נכללה בגרסה המקוונת");
    throw new Error("לא זמין");
  }
  const url = new URL(path, location.origin);
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && url.searchParams.set(k, v));
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `שגיאה ${r.status}`);
  return r.arrayBuffer();
}

export const isStatic = STATIC;
export async function upload(file) {
  if (STATIC) throw new Error("העלאת קבצים זמינה באפליקציה המקומית");
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "ההעלאה נכשלה");
  return r.json();
}
