"""Decision Support AI — database-grounded, deterministic question answering.

Design (security + accuracy):
  * Every figure comes from allow-listed, parameterised analytical queries (app.services.analytics) on the READ-ONLY
    connection with a short statement timeout. No free-form SQL is ever generated from user text.
  * Intent is detected with transparent rules; every answer carries its calculation methodology and scope.
  * The active dashboard filters and the user's division permissions are always applied.
  * Optional LLM layer (LLM_ENABLED) may only *rephrase* the deterministic result; it receives the computed facts
    and is instructed not to add numbers. If it is unavailable the deterministic answer is returned unchanged.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.request
from dataclasses import dataclass, field

from sqlalchemy import text

from app.config import get_settings
from app.db.session import read_engine
from app.security.auth import CurrentUser
from app.services.analytics import Analytics, Filters, block
from app.services.cache import cache

log = logging.getLogger("medd.chat")
E = html.escape

# Approved business rules (from MEDD 1.0 code — see docs/03_KPI_DEFINITIONS.md)
CRITICAL_UTIL = 25.0          # GAP_BANDS: < 25% = Critical
LOW_UTIL = 50.0               # 25–50% = Low
AMC_ADEQUATE = 70.0           # buildAnalysisRecs: AMC coverage < 70% -> warning
COST_TIERS = [("A · Unit Cost &gt; ₹1,00,000", 100000), ("B · Unit Cost &gt; ₹5,00,000", 500000),
              ("C · Unit Cost &gt; ₹10,00,000", 1000000)]


def fmt(n) -> str:
    if n is None:
        return "—"
    n = int(round(float(n)))
    s = str(abs(n))
    if len(s) > 3:  # Indian grouping
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + s


def sfmt(n) -> str:
    return "—" if n is None else (("+" if n > 0 else "−" if n < 0 else "") + fmt(abs(n)))


def cr(n) -> str:
    return "—" if n is None else f"₹{float(n) / 1e7:,.1f} Cr"


@dataclass
class Answer:
    html: str
    intent: str
    methodology: list[str] = field(default_factory=list)
    scope: str = ""
    entities: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)

    def render(self) -> str:
        meth = "".join(f"<li>{m}</li>" for m in self.methodology)
        foot = (f'<details class="cbmeth"><summary>How this was calculated</summary><ul>{meth}</ul>'
                f'<div class="muted">Scope: {E(self.scope)} · source: PostgreSQL analytics.mv_line_fact</div></details>')
        return self.html + foot


def kv(pairs) -> str:
    return "<table>" + "".join(f'<tr><td style="color:var(--mut)">{E(str(a))}</td><td class="num"><b>{E(str(b))}</b></td></tr>'
                               for a, b in pairs) + "</table>"


def table(cols, rows, drill_equipment=False) -> str:
    h = "".join(f'<th class="{"num" if i else ""}">{E(c)}</th>' for i, c in enumerate(cols))
    body = ""
    for r in rows:
        cells = "".join(f'<td class="{"num" if i else ""}">{E(str(v))}</td>' for i, v in enumerate(r))
        if drill_equipment:
            body += (f'<tr data-eq="{E(str(r[0]))}" class="cbdrillrow" style="cursor:pointer" '
                     f'title="Drill this equipment: Division → Institute → Department → Equipment">{cells}</tr>')
        else:
            body += f"<tr>{cells}</tr>"
    return f'<table class="cbdrill"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>'


def rec(t: str) -> str:
    return f'<div class="rec">{t}</div>'


def _names(user: CurrentUser) -> dict:
    def load():
        with read_engine.connect() as c:
            q = lambda s: [r[0] for r in c.execute(text(s))]  # noqa: E731
            return {"equipment": q("SELECT DISTINCT equipment FROM analytics.mv_line_fact"),
                    "institute": q("SELECT DISTINCT institute FROM analytics.mv_line_fact"),
                    "division": q("SELECT name FROM master_data.division"),
                    "department": q("SELECT DISTINCT department FROM analytics.mv_line_fact"),
                    "aliases": [(r[0], r[1], r[2]) for r in c.execute(text(
                        "SELECT entity_type, alias_key, canonical_name FROM master_data.name_alias"))]}
    from app.services.analytics import data_status
    return cache.get_or_set(("chat_names", data_status()["data_version"]), load)


class ChatEngine:
    def __init__(self, user: CurrentUser, filters: Filters, conn=None):
        self.user, self.f = user, filters
        self.A = Analytics(user, conn)
        self.fin = user.can("financial:read")

    # -------------------------------------------------------------- entity recognition
    def _find(self, ql: str, names: list[str], min_word: int = 3) -> list[str]:
        hits = [n for n in names if f" {n.lower()} " in ql or (len(n) > 5 and n.lower() in ql)]
        if hits:
            return sorted(hits, key=len, reverse=True)
        out = []
        for n in names:
            words = [w for w in re.split(r"[^a-z0-9]+", n.lower()) if len(w) >= min_word and w not in STOP]
            if words and all(re.search(rf"\b{re.escape(w)}", ql) for w in words):
                out.append(n)
        return sorted(out, key=len, reverse=True)

    def recognise(self, q: str) -> dict:
        ql = " " + re.sub(r"\s+", " ", q.lower()) + " "
        N = _names(self.user)
        divs = []
        for d in N["division"]:
            key = d.lower().replace("chh.", "").strip()
            first = d.split(" ")[0].lower().rstrip(".")
            if f" {d.lower()} " in ql or f" {key} " in ql or (len(first) > 3 and re.search(rf"\b{re.escape(first)}\b", ql)):
                divs.append(d)
        for et, ak, cn in N["aliases"]:
            if et == "division" and re.search(rf"\b{re.escape(ak)}\b", ql) and cn not in divs:
                divs.append(cn)
        if "sambhaji" in ql or "aurangabad" in ql:
            divs += [d for d in N["division"] if "Sambhaji" in d and d not in divs]
        insts = self._find(ql, N["institute"])
        for et, ak, cn in N["aliases"]:
            if et == "institute" and f" {ak} " in ql and cn not in insts:
                insts.append(cn)
        depts = [d for d in N["department"] if re.search(rf"(?<![a-z]){re.escape(d.lower())}(?![a-z])", ql)]
        eqs = self._find(ql, N["equipment"])
        weak = False
        if not eqs and not (insts or depts or divs):  # distinctive keyword fallback (MEDD 1.0 behaviour)
            weak = True
            qwords = [w for w in re.split(r"[^a-z0-9]+", ql) if len(w) > 4 and w not in STOP]
            eqs = [n for n in N["equipment"] if any(re.search(rf"\b{re.escape(w)}", n.lower()) for w in qwords)]
            eqs = sorted(eqs, key=len)[:12]
        # an institute name contains its city (= division name) — don't double count
        if insts:
            divs = [d for d in divs if not any(d.lower() in i.lower() for i in insts)]
        return {"division": divs, "institute": insts[:3], "department": depts[:3], "equipment": eqs, "weak_equipment": weak}

    # -------------------------------------------------------------- helpers
    def _scoped(self, **extra) -> Filters:
        f = Filters(**{k: list(getattr(self.f, k)) for k in ("division", "institute", "department", "subcat",
                                                             "equipment", "bedded")})
        for k, v in extra.items():
            if v:
                cur = getattr(f, k)
                setattr(f, k, [x for x in v if not cur or x in cur] or ["__none__"])
        f.apply_user_scope(self.user)
        return f

    def _scope_label(self, f: Filters) -> str:
        parts = []
        for k, lbl in (("division", "Division"), ("institute", "Institute"), ("department", "Department"),
                       ("subcat", "Sub-category"), ("equipment", "Equipment"), ("bedded", "Bedded")):
            v = getattr(f, k)
            if v:
                parts.append(f"{lbl}: " + (", ".join(map(str, v[:3])) + (f" +{len(v) - 3}" if len(v) > 3 else "")))
        if self.user.allowed_divisions is not None:
            parts.append("permitted divisions only")
        return " · ".join(parts) or "Maharashtra (all institutes)"

    BASE_METH = ["Utilisation % = Σ Functional ÷ Σ Required (NMC MSR) × 100 (≥100% = norm met).",
                 "Net Requirement = Σ Required − Σ Functional (+ shortfall / − surplus).",
                 "Budget = Σ (Proposed procurement × unit cost)."]

    def _summary_kv(self, b: dict) -> str:
        pairs = [["Equipment required (NMC MSR)", fmt(b["required"])], ["Available", fmt(b["available"])],
                 ["Functional", fmt(b["functional"])], ["Non-functional", fmt(b["non_functional"])],
                 ["Net requirement", sfmt(b["net_requirement"])], ["Functional shortfall", fmt(b["functional_shortfall"])],
                 ["Utilisation %", f'{b["gap_pct"]}%'], ["Procurement suggested by colleges", fmt(b["procurement"])]]
        if self.fin:
            pairs.append(["Estimated budget", cr(b["budget"])])
        return kv(pairs)

    # -------------------------------------------------------------- intents
    def answer(self, q: str) -> Answer:
        ql = " " + q.lower() + " "
        ent = self.recognise(q)
        top_n = int((re.search(r"top\s*(\d+)", ql) or [None, "10"])[1])
        top_n = max(1, min(top_n, 50))

        def has(*w):
            return any(x in ql for x in w)

        if has("summary", "overview", "overall", "total equipment gap", "across maharashtra", "state-wide", "statewide") \
                and not ent["institute"] and not ent["division"] and not ent["department"]:
            return self.summary()
        if has("compare", " vs ", "versus") and len(ent["division"]) >= 2:
            return self.compare_divisions(ent["division"])
        if has("compare", " vs ", "versus") and len(ent["institute"]) >= 2:
            return self.compare(ent["institute"], "institute")
        if re.search(r"top\s*\d*", ql) and has("cost tier", "tier", "net requirement", "net req") and not ent["institute"]:
            return self.cost_tiers(top_n, ent)
        if has("immediate", "urgent", "priority", "prioritise", "prioritize", "critical"):
            return self.priority(top_n, ent)
        if has("end of life", "end-of-life", "eol", "approaching end", "replacement"):
            return self.ranking("equipment", "end_of_life", "Equipment approaching end of life (<1 FY of service left)",
                                top_n, ent, "Quantity approaching end of life, as reported per line item.")
        if has("amc", "cmc", "maintenance contract"):
            return self.amc(top_n, ent)
        if has("non-functional", "non functional", "nonfunctional", "not working", "broken"):
            lvl = "division" if has("division") else "equipment" if has("equipment") and not has("institute") else "institute"
            return self.ranking(lvl, "non_functional", f"{lvl.title()}s with the most non-functional equipment", top_n, ent,
                                "Non-functional = Σ Available − Σ Functional.")
        if has("condemn"):
            return self.ranking("institute" if not has("division") else "division", "condemnation",
                                "Proposed condemnation", top_n, ent, "Quantity proposed for condemnation.")
        if has("shortage", "shortfall", "highest gap", "biggest gap", "worst", "lowest utilisation", "lowest utilization"):
            lvl = ("division" if has("division") else "department" if has("department") else
                   "equipment" if has("equipment") and not ent["equipment"] else "institute")
            return self.ranking(lvl, "functional_shortfall", f"{lvl.title()}s with the largest functional shortfall",
                                top_n, ent, "Functional shortfall = Σ max(Required − Functional, 0) at line level "
                                            "(units still needed to meet the NMC MSR norm; surpluses elsewhere are not netted).")
        if has("budget", "cost", "financial", "crore", "expenditure") and not ent["equipment"]:
            return self.budget(ent)
        if ent["equipment"] and not has("summary", "overview", "overall"):
            return self.equipment(ent)
        if ent["institute"]:
            return self.scope_card("institute", ent["institute"][0])
        if ent["department"] and not ent["division"]:
            return self.scope_card("department", ent["department"][0])
        if ent["division"]:
            if ent["department"]:
                return self.scope_card("department", ent["department"][0], division=ent["division"])
            return self.scope_card("division", ent["division"][0])
        if has("summary", "overall", "overview", "total", "gap", "utilis", "utiliz", "maharashtra", "state"):
            return self.summary()
        if has("procure", "purchase", "buy"):
            return self.ranking("division", "procurement", "Procurement proposed by colleges", top_n, ent,
                                "Quantity proposed for new procurement, as suggested by colleges.")
        return Answer("I couldn't match that to an equipment, division, institute or department, or to one of the "
                      "analyses I support. Try e.g. <i>“total equipment gap”</i>, <i>“divisions with highest shortages”</i>, "
                      "<i>“institutes with most non-functional equipment”</i>, <i>“Ventilator in Pune”</i>, "
                      "<i>“compare Pune and Nagpur”</i>, <i>“inadequate AMC coverage”</i> or "
                      "<i>“top 10 net requirement by cost tier”</i>.", "fallback", ["No data was queried."],
                      self._scope_label(self.f))

    def summary(self) -> Answer:
        b = self.A.summary(self.f)
        divs = self.A.breakdown(self.f, "division", sort="gap_pct", direction="asc")
        divs = [d for d in divs if d["required"] > 0]
        h = f"<b>Equipment gap summary — {E(self._scope_label(self.f))} ({E(get_settings().fy_label)}):</b>" + self._summary_kv(b)
        if b["required"] == 0 and b["line_items"] == 0:
            h += rec("No line items match the current filters.")
        elif divs:
            w = divs[0]
            h += rec(f"🩺 Lowest utilisation division: <b>{E(w['name'])}</b> at {w['gap_pct']}% "
                     f"(functional shortfall {fmt(w['functional_shortfall'])} units, net requirement {sfmt(w['net_requirement'])}). Prioritise there.")
        if b["net_requirement"] < 0:
            h += rec("ℹ️ The net requirement is negative because functional stock exceeds the NMC MSR norm in aggregate; "
                     f"the <b>functional shortfall</b> ({fmt(b['functional_shortfall'])} units) shows where equipment is still missing.")
        return Answer(h, "summary", self.BASE_METH + ["Functional shortfall = Σ max(Required − Functional, 0) per line item."],
                      self._scope_label(self.f), data={"summary": b})

    def ranking(self, level: str, key: str, title: str, n: int, ent: dict, meth: str) -> Answer:
        f = self._scoped(division=ent["division"], department=ent["department"], institute=ent["institute"])
        rows = [r for r in self.A.breakdown(f, level, sort=key, direction="desc") if (r.get(key) or 0) > 0][:n]
        cols = [level.title(), title.split(" (")[0] if len(title) < 30 else key.replace("_", " ").title(),
                "Required", "Functional", "Utilisation %"]
        body = [[r["name"], fmt(r[key]), fmt(r["required"]), fmt(r["functional"]), f"{r['gap_pct']}%"] for r in rows]
        h = f"<b>{E(title)} — top {len(rows)}</b>" + (table(cols, body, drill_equipment=level == "equipment") if rows
                                                      else rec("No matching records in this scope."))
        if rows:
            h += rec(f"🔎 Highest: <b>{E(rows[0]['name'])}</b> with {fmt(rows[0][key])}.")
        return Answer(h, f"ranking:{level}:{key}", [meth, "Ranked descending; only entries with a value > 0 are listed."],
                      self._scope_label(f), data={"rows": rows})

    def budget(self, ent: dict) -> Answer:
        if not self.fin:
            return Answer("Budget and unit-cost figures are restricted for your role.", "budget:denied",
                          ["Permission financial:read required."], self._scope_label(self.f))
        f = self._scoped(division=ent["division"], institute=ent["institute"], department=ent["department"])
        b = self.A.summary(f)
        divs = self.A.breakdown(f, "division", sort="budget", direction="desc")
        eqs = self.A.breakdown(f, "equipment", sort="budget", direction="desc", limit=10)
        h = (f"<b>Estimated procurement budget: {cr(b['budget'])}</b> (₹{fmt(b['budget'])}) for "
             f"{fmt(b['procurement'])} units proposed — {E(self._scope_label(f))}.")
        h += table(["Division", "Budget", "Procurement", "Share"],
                   [[d["name"], cr(d["budget"]), fmt(d["procurement"]),
                     f"{(d['budget'] / b['budget'] * 100 if b['budget'] else 0):.1f}%"] for d in divs if d["budget"]])
        h += "<div style='margin-top:8px'><b>Largest budget lines (equipment):</b></div>" + table(
            ["Equipment", "Units", "Unit cost", "Budget"],
            [[e["name"], fmt(e["procurement"]), cr(e["unit_cost"]), cr(e["budget"])] for e in eqs], drill_equipment=True)
        return Answer(h, "budget", ["Budget = Σ (Proposed procurement × unit cost) over all line items in scope.",
                                    "Equipment without a unit cost contributes ₹0 (listed in the ingestion report)."],
                      self._scope_label(f), data={"summary": b})

    def amc(self, n: int, ent: dict) -> Answer:
        f = self._scoped(division=ent["division"], department=ent["department"])
        b = self.A.summary(f)
        insts = [r for r in self.A.breakdown(f, "institute", sort="amc_pct", direction="asc") if r["functional"] > 0]
        low = [r for r in insts if r["amc_pct"] < AMC_ADEQUATE]
        h = (f"<b>AMC/CMC coverage {b['amc_pct']}%</b> — {fmt(b['amc'])} of {fmt(b['functional'])} functional units "
             f"under active AMC/CMC ({E(self._scope_label(f))}). <b>{len(low)}</b> of {len(insts)} institutes are below "
             f"{AMC_ADEQUATE:.0f}%.")
        h += table(["Institute", "AMC %", "Under AMC", "Functional", "Uncovered"],
                   [[r["name"], f"{r['amc_pct']}%", fmt(r["amc"]), fmt(r["functional"]), fmt(r["functional"] - r["amc"])]
                    for r in low[:n]])
        return Answer(h, "amc", ["AMC % = Σ units under active AMC/CMC ÷ Σ Functional × 100.",
                                 f"Inadequate = below {AMC_ADEQUATE:.0f}% (threshold used by the MEDD 1.0 AMC recommendations)."],
                      self._scope_label(f), data={"rows": low[:n]})

    def priority(self, n: int, ent: dict) -> Answer:
        f = self._scoped(division=ent["division"], institute=ent["institute"])
        deps = self.A.breakdown(f, "department", sort="functional_shortfall", direction="desc")
        crit = [d for d in deps if d["required"] > 0 and d["gap_pct"] < CRITICAL_UTIL and d["net_requirement"] > 0]
        low = [d for d in deps if d["required"] > 0 and CRITICAL_UTIL <= d["gap_pct"] < LOW_UTIL and d["net_requirement"] > 0]
        eqs = [e for e in self.A.breakdown(f, "equipment", sort="functional_shortfall", direction="desc")
               if e["required"] > 0 and e["gap_pct"] < CRITICAL_UTIL and e["functional_shortfall"] > 0][:n]
        h = f"<b>Priority procurement — {E(self._scope_label(f))}</b>"
        h += f"<div style='margin-top:6px'><b>Departments in the Critical band (&lt;{CRITICAL_UTIL:.0f}% utilisation):</b> {len(crit)}</div>"
        h += table(["Department", "Utilisation %", "Shortfall", "Proposed", "Budget"],
                   [[d["name"], f"{d['gap_pct']}%", fmt(d["functional_shortfall"]), fmt(d["procurement"]), cr(d["budget"])]
                    for d in crit[:n]]) if crit else rec("No department is in the Critical band in this scope.")
        if low:
            h += f"<div style='margin-top:6px'><b>Low band (25–50%):</b> " + ", ".join(E(d["name"]) for d in low[:8]) + "</div>"
        h += f"<div style='margin-top:8px'><b>Critical-band equipment with the largest shortfall:</b></div>" + table(
            ["Equipment", "Utilisation %", "Shortfall", "Unit cost", "Est. cost of shortfall"],
            [[e["name"], f"{e['gap_pct']}%", fmt(e["functional_shortfall"]), cr(e["unit_cost"]),
              cr(e["functional_shortfall"] * (e["unit_cost"] or 0)) if self.fin else "—"] for e in eqs], drill_equipment=True)
        return Answer(h, "priority", [
            f"Priority rule = MEDD severity bands: Critical < {CRITICAL_UTIL:.0f}% utilisation, Low {CRITICAL_UTIL:.0f}–{LOW_UTIL:.0f}%, "
            "restricted to entries with a positive net requirement, ranked by functional shortfall.",
            "Est. cost of shortfall = functional shortfall × unit cost (indicative; colleges' own proposals may differ).",
            "This is a ranking aid, not a sanction decision — field-verify before procurement."],
            self._scope_label(f), data={"departments": crit[:n], "equipment": eqs})

    def cost_tiers(self, n: int, ent: dict) -> Answer:
        f = self._scoped(division=ent["division"], institute=ent["institute"], department=ent["department"])
        cat = self.A.breakdown(f, "equipment", sort="net_requirement", direction="desc")
        h = f"<b>Top {n} Net Requirement equipment by cost tier ({E(self._scope_label(f))}):</b>"
        for label, mn in COST_TIERS:
            rows = [e for e in cat if (e.get("unit_cost") or 0) > mn and e["net_requirement"] > 0][:n]
            h += f"<div style='margin-top:10px'><b>{label}</b>"
            h += table(["Equipment", "Req", "Func", "Net Req", "Unit Cost", "Est. Cost"],
                       [[e["name"], fmt(e["required"]), fmt(e["functional"]), sfmt(e["net_requirement"]),
                         cr(e["unit_cost"]), cr(max(0, e["net_requirement"]) * (e["unit_cost"] or 0)) if self.fin else "—"]
                        for e in rows], drill_equipment=True) if rows else " <span class='muted'>— none in this scope</span>"
            h += "</div>"
        return Answer(h, "cost_tiers", ["Tiers by unit cost (> ₹1 lakh, > ₹5 lakh, > ₹10 lakh) — MEDD 1.0 rule.",
                                        "Ranked by Net Requirement; Est. Cost = max(Net Requirement, 0) × unit cost."],
                      self._scope_label(f))

    def compare_divisions(self, divs: list[str]) -> Answer:
        return self.compare(divs, "division")

    def compare(self, names: list[str], level: str) -> Answer:
        f = self._scoped(**{level: names})
        rows = {r["name"]: r for r in self.A.breakdown(f, level)}
        sel = [rows[n] for n in names if n in rows]
        metrics = [("Required", "required", fmt), ("Available", "available", fmt), ("Functional", "functional", fmt),
                   ("Non-functional", "non_functional", fmt), ("Net requirement", "net_requirement", sfmt),
                   ("Functional shortfall", "functional_shortfall", fmt), ("Utilisation %", "gap_pct", lambda v: f"{v}%"),
                   ("Availability (func %)", "func_pct", lambda v: f"{v}%"), ("Procurement", "procurement", fmt),
                   ("AMC %", "amc_pct", lambda v: f"{v}%"), ("End of life", "end_of_life", fmt)]
        if self.fin:
            metrics.append(("Budget", "budget", cr))
        h = f"<b>Comparison of {', '.join(E(s['name']) for s in sel)}</b>" + table(
            ["Metric"] + [s["name"] for s in sel], [[m[0]] + [m[2](s[m[1]]) for s in sel] for m in metrics])
        if len(sel) >= 2:
            best = max(sel, key=lambda s: s["gap_pct"])
            worst = min(sel, key=lambda s: s["gap_pct"])
            h += rec(f"⚖️ Higher utilisation: <b>{E(best['name'])}</b> ({best['gap_pct']}%); lower: <b>{E(worst['name'])}</b> "
                     f"({worst['gap_pct']}%), shortfall {fmt(worst['functional_shortfall'])} units.")
        return Answer(h, f"compare:{level}", self.BASE_METH + ["Func % = Σ Functional ÷ Σ Available × 100."],
                      self._scope_label(f), data={"rows": sel})

    def scope_card(self, level: str, name: str, division: list[str] | None = None) -> Answer:
        kw = {"division": division or []}
        kw[level] = [name]
        f = self._scoped(**kw)
        b = self.A.summary(f)
        h = f"<b>{E(name)}</b> ({level}) — {E(get_settings().fy_label)}" + self._summary_kv(b)
        top = [e for e in self.A.breakdown(f, "equipment", sort="functional_shortfall", direction="desc", limit=8)
               if e["functional_shortfall"] > 0][:5]
        if top:
            h += "<div style='margin-top:8px'><b>Top equipment needs here:</b>" + table(
                ["Equipment", "Req", "Func", "Net Req", "Unit Cost", "Est. Cost"],
                [[e["name"], fmt(e["required"]), fmt(e["functional"]), sfmt(e["net_requirement"]), cr(e["unit_cost"]),
                  cr(max(0, e["net_requirement"]) * (e["unit_cost"] or 0)) if self.fin else "—"] for e in top],
                drill_equipment=True) + "</div>"
        h += rec(f"🛒 Net requirement {sfmt(b['net_requirement'])} units (functional shortfall {fmt(b['functional_shortfall'])}); "
                 f"colleges suggested {fmt(b['procurement'])}." + (f" Estimated budget {cr(b['budget'])}." if self.fin else ""))
        return Answer(h, f"scope:{level}", self.BASE_METH, self._scope_label(f), {level: name}, {"summary": b})

    def equipment(self, ent: dict) -> Answer:
        eq = ent["equipment"]
        # prefer the most decision-relevant match (highest net requirement), as MEDD 1.0 did
        cands = self.A.breakdown(self._scoped(equipment=eq[:12]), "equipment", sort="net_requirement", direction="desc")
        if not cands:
            return Answer(f"No line items for <b>{E(eq[0])}</b> in the current scope.", "equipment",
                          ["No matching rows."], self._scope_label(self.f))
        e = cands[0]
        loc = {k: ent[k] for k in ("division", "institute", "department") if ent[k]}
        f = self._scoped(equipment=[e["name"]], **loc)
        b = self.A.summary(f)
        b["unit_cost"] = e.get("unit_cost")
        h = f"<b>{E(e['name'])}</b> — {E(self._scope_label(f))}" + self._summary_kv(b)
        if self.fin:
            h = h.replace("</table>", f'<tr><td style="color:var(--mut)">Unit cost</td><td class="num"><b>{cr(e.get("unit_cost"))}</b></td></tr></table>', 1)
        if not loc:
            divs = self.A.breakdown(f, "division", sort="functional_shortfall", direction="desc")
            h += "<div style='margin-top:8px'><b>By division:</b>" + table(
                ["Division", "Req", "Func", "Net Req", "Proc.", "Utilisation %"],
                [[d["name"], fmt(d["required"]), fmt(d["functional"]), sfmt(d["net_requirement"]), fmt(d["procurement"]),
                  f"{d['gap_pct']}%"] for d in divs]) + "</div>"
        h += rec(self._recommend(b))
        if len(cands) > 1:
            h += f"<div class='muted' style='margin-top:6px'>Other matches: {E(', '.join(c['name'] for c in cands[1:6]))}</div>"
        return Answer(h, "equipment", self.BASE_METH + [
            "Procurement check: suggestion > 1.25 × net requirement → verify; < 0.75 × → may under-provision (MEDD 1.0 rule)."],
            self._scope_label(f), {"equipment": e["name"], **loc}, {"summary": b})

    @staticmethod
    def _recommend(b: dict) -> str:
        net, sug = b["net_requirement"], b["procurement"]
        if net <= 0:
            return (f"✅ Functional stock meets the NMC MSR norm in this scope — <b>no net procurement needed</b>. "
                    f"Colleges suggested {fmt(sug)} units; review before sanctioning.")
        msg = f"🛒 Net requirement is <b>{fmt(net)}</b> units to reach the norm. Colleges suggested <b>{fmt(sug)}</b>. "
        if sug > net * 1.25:
            msg += "College suggestion exceeds net need by a wide margin — verify before sanctioning."
        elif sug < net * 0.75:
            msg += "College suggestion is below the computed net need — may under-provision."
        else:
            msg += "College suggestion is broadly in line with the net requirement."
        return msg


STOP = {"what", "which", "where", "about", "total", "show", "there", "their", "these", "those", "budget", "required",
        "requirement", "equipment", "division", "divisions", "institute", "institutes", "department", "departments",
        "maharashtra", "compare", "between", "highest", "lowest", "number", "status", "procurement", "estimated",
        "approaching", "coverage", "functional", "available", "summary", "overall", "please", "machine"}


def llm_rephrase(question: str, ans: Answer) -> str | None:
    s = get_settings()
    if not (s.llm_enabled and s.anthropic_api_key):
        return None
    facts = json.dumps({"question": question, "intent": ans.intent, "scope": ans.scope, "data": ans.data},
                       default=str)[:12000]
    body = json.dumps({"model": s.llm_model, "max_tokens": 300, "system":
                       "You summarise database results for senior health-department officials. Use ONLY numbers present "
                       "in the JSON facts; never estimate, infer or add figures. 2-4 sentences, plain text.",
                       "messages": [{"role": "user", "content": facts}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=s.llm_timeout_seconds) as r:
            out = json.loads(r.read())
        return "".join(c.get("text", "") for c in out.get("content", []))
    except Exception as exc:  # deterministic fallback
        log.warning("LLM unavailable (%s) — deterministic answer only", exc)
        return None


def ask(user: CurrentUser, question: str, filters: Filters) -> dict:
    q = (question or "").strip()[:500]
    if not q:
        return {"html": "Please type a question.", "intent": "empty"}
    with read_engine.connect() as conn:   # read-only role, read-only transaction, short timeout
        conn.execute(text(f"SET LOCAL statement_timeout = {int(get_settings().chat_statement_timeout_ms)}"))
        ans = ChatEngine(user, filters, conn).answer(q)
    out = {"html": ans.render(), "intent": ans.intent, "scope": ans.scope, "methodology": ans.methodology,
           "entities": ans.entities, "ai_summary": None, "mode": "deterministic"}
    summ = llm_rephrase(q, ans)
    if summ:
        out["ai_summary"] = summ
        out["mode"] = "deterministic+llm"
        out["html"] = (f'<div class="rec">🤖 {E(summ)}<div class="muted" style="font-size:11px">AI wording; every '
                       f'figure is from the tables below.</div></div>') + out["html"]
    return out
