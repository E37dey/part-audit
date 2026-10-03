// REST client. In the published demo (window.PA_STATIC) the same calls read pre-exported files and
// decisions are kept in this browser tab only.
const STATIC = !!window.PA_STATIC;
const memDecisions = [];
const staticCache = {};

function staticFile(file, kind = "json") {
  const key = `${kind}:${file}`;
  if (!staticCache[key]) {
    staticCache[key] = fetch(`data/${file}`).then((r) => {
      if (!r.ok) throw new Error("הנתון לא נכלל בגרסת ההדגמה המקוונת");
      return kind === "json" ? r.json() : r.arrayBuffer();
    });
  }
  return staticCache[key];
}
const staticJson = (file) => staticFile(file);

const latestDecision = (kind, id) => [...memDecisions].reverse().find((x) => x.target_type === kind && x.target_id === id);
const historyOf = (kind, id) => memDecisions.filter((x) => x.target_type === kind && x.target_id === id).reverse()
  .map((d) => ({ ...d, master_uid: d.master_uid || "" }));

async function pnOf(uid) {
  if (!staticCache.pnMap) staticCache.pnMap = staticJson("parts.json").then((rows) => Object.fromEntries(rows.map((r) => [r.uid, r.pn])));
  return (await staticCache.pnMap)[uid] || "";
}

async function applyDecisions(rows, kind) {
  if (!STATIC || !Array.isArray(rows)) return rows;
  const out = [];
  for (const r of rows) {
    const d = latestDecision(kind, r.id);
    if (!d) { out.push(r); continue; }
    const row = { ...r, decision: d.decision, decision_note: d.note, decision_by: d.user, decision_at: d.created,
      decision_master: d.master_uid || "" };
    if (kind === "group") row.final_master_pn = (d.master_uid && (await pnOf(d.master_uid))) || r.master_pn;
    out.push(row);
  }
  return out;
}

// the same rule as decisions.effective_mapping: a group decision may name another target part number
async function effectiveMapping(rows) {
  const details = await staticJson("group_details.json");
  const overridden = new Set();
  const extra = [];
  for (const [gid, g] of Object.entries(details)) {
    const d = latestDecision("group", gid);
    const target = d?.master_uid;
    const t = target && g.parts.find((x) => x.uid === target);
    if (!t || !t.pn || target === g.master_uid) continue;
    overridden.add(gid);
    const key = (pn) => String(pn).toUpperCase().replace(/[^A-Z0-9]/g, "");
    const seen = new Set([key(t.pn)]);
    for (const r of g.parts) {
      if (!r.pn || seen.has(key(r.pn))) continue;
      seen.add(key(r.pn));
      const pair = g.pairs.find((x) => (x.a === r.uid && x.b === target) || (x.b === r.uid && x.a === target));
      extra.push({ id: `M~${gid}~${r.pn}~${t.pn}`, group_id: gid, old_pn: r.pn, old_uid: r.uid, old_name: r.name,
        old_source: r.source, new_pn: t.pn, new_uid: target, new_name: t.name, reason_he: pair ? pair.reason_he : g.reason_he,
        why_target_he: `נבחר על ידי ${d.user}`, confidence: pair ? pair.confidence : g.confidence,
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
  if ((m = p.match(/^runs\/[^/]+\/summary$/))) {
    const s = await staticJson("summary.json");
    const top = await applyDecisions(s.top_groups, "group");
    const decided = new Set(memDecisions.filter((d) => d.target_type === "group").map((d) => d.target_id));
    const approved = new Set(memDecisions.filter((d) => d.target_type === "group" && latestDecision("group", d.target_id)?.decision === "approve").map((d) => d.target_id));
    return { ...s, top_groups: top, decisions: { pending_groups: Math.max(0, s.decisions.pending_groups - decided.size),
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
    const rows = await applyDecisions(await effectiveMapping(await staticJson("mapping.json")), "mapping");
    return rows.map((r) => {
      if (r.decision && !r.inherited) return r;
      const g = latestDecision("group", r.group_id);
      return g ? { ...r, decision: g.decision, decision_by: g.user, decision_at: g.created, decision_note: g.note, inherited: true } : r;
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
      ids.forEach((id) => memDecisions.push({ ...body, target_id: id, created: now, user: body.user || "צופה בהדגמה" }));
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
