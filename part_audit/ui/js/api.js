// REST client. In the published demo (window.PA_STATIC) the same calls read pre-exported files and
// decisions are kept in this browser tab only.
const STATIC = !!window.PA_STATIC;
const memDecisions = [];
let staticCache = {};

async function staticJson(file) {
  if (!staticCache[file]) {
    staticCache[file] = fetch(`data/${file}`).then((r) => {
      if (!r.ok) throw new Error("הנתון לא קיים בגרסת ההדגמה");
      return r.json();
    });
  }
  return staticCache[file];
}
const safe = (s) => String(s).replace(/[^A-Za-z0-9_.-]/g, "_");

function applyDecisions(rows, kind) {
  if (!STATIC || !Array.isArray(rows)) return rows;
  return rows.map((r) => {
    const d = [...memDecisions].reverse().find((x) => x.target_type === kind && x.target_id === r.id);
    return d ? { ...r, decision: d.decision, decision_note: d.note, decision_by: d.user, decision_at: d.created } : r;
  });
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
    const top = applyDecisions(s.top_groups, "group");
    const dec = memDecisions.filter((d) => d.target_type === "group");
    return { ...s, top_groups: top, decisions: { ...s.decisions, pending_groups: Math.max(0, s.decisions.pending_groups - new Set(dec.map((d) => d.target_id)).size) } };
  }
  if ((m = p.match(/^runs\/[^/]+\/groups$/))) return applyDecisions(await staticJson("groups.json"), "group");
  if ((m = p.match(/^runs\/[^/]+\/groups\/(.+)$/))) {
    const all = await staticJson("group_details.json");
    const g = all[decodeURIComponent(m[1])];
    if (!g) throw new Error("הקבוצה לא נמצאה");
    return applyDecisions([g], "group")[0];
  }
  if ((m = p.match(/^runs\/[^/]+\/pairs$/))) {
    const rows = await staticJson("pairs.json");
    const cats = params.category ? new Set(params.category.split(",")) : null;
    return applyDecisions(cats ? rows.filter((r) => cats.has(r.category)) : rows, "pair");
  }
  if ((m = p.match(/^runs\/[^/]+\/pairs\/(.+)$/))) {
    const all = await staticJson("pair_details.json");
    const x = all[decodeURIComponent(m[1])];
    if (!x) throw new Error("הזוג לא נמצא");
    return applyDecisions([x], "pair")[0];
  }
  if ((m = p.match(/^runs\/[^/]+\/findings\/(\w+)$/))) return applyDecisions(await staticJson(`findings_${m[1]}.json`), "issue");
  if ((m = p.match(/^runs\/[^/]+\/mapping$/))) {
    const rows = applyDecisions(await staticJson("mapping.json"), "mapping");
    return rows.map((r) => {
      if (r.decision) return r;
      const g = [...memDecisions].reverse().find((d) => d.target_type === "group" && d.target_id === r.group_id);
      return g ? { ...r, decision: g.decision, decision_by: g.user, decision_at: g.created, inherited: true } : r;
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
  if ((m = p.match(/^align\/[^/]+$/))) {
    const all = await staticJson("align.json");
    const x = all[`${params.a}|${params.b}`];
    if (!x) throw new Error("לא זמין בגרסת ההדגמה");
    return x;
  }
  if ((m = p.match(/^runs\/[^/]+\/parts\/(.+)$/))) {
    const all = await staticJson("part_details.json");
    const x = all[decodeURIComponent(m[1])];
    if (!x) throw new Error("החלק לא נמצא");
    return x;
  }
  throw new Error("לא זמין בגרסת ההדגמה");
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
    if ((m = path.match(/^\/api\/mesh\/[^/]+\/(.+)$/))) return fetchBin(`data/mesh/${safe(decodeURIComponent(m[1]))}.pam`);
    if (path.startsWith("/api/compare/")) return fetchBin(`data/compare/${safe(params.a)}__${safe(params.b)}${params.mirror ? "__m" : ""}.pac`);
    throw new Error("לא זמין");
  }
  const url = new URL(path, location.origin);
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && url.searchParams.set(k, v));
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `שגיאה ${r.status}`);
  return r.arrayBuffer();
}
async function fetchBin(file) {
  const r = await fetch(file);
  if (!r.ok) throw new Error("תצוגה תלת-ממדית לא נכללה בגרסת ההדגמה עבור החלק הזה");
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
