#!/usr/bin/env python3
"""Synthesis stage: projects MASTER_DATASET facts through a predeclared mapping registry (MR-1)
and grades domains by primary cultural cluster. Writes SYNTHESIS.json. No prose interpretation.

Usage: python synthesize.py <dir>
"""
import json, os, sys
from datetime import date, datetime

D = sys.argv[1]
M = json.load(open(os.path.join(D, "MASTER_DATASET.json")))
AS_OF = date.fromisoformat(json.load(open(os.path.join(D, "BIRTH_INPUT.json")))["normalized"]["as_of_date"])
BIRTH = date.fromisoformat(M["input_audit"]["normalized_civil"][:10])
HORIZON = date(AS_OF.year + 4, 12, 31)
SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
         "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
LORD = ["Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury", "Venus", "Mars", "Jupiter",
        "Saturn", "Saturn", "Jupiter"]

# ------------------------------------------------------------------ mapping registry MR-1
REGISTRY = {
    "id": "MR-1",
    "note": "Declared by this analysis before grading; not a canonical traditional registry.",
    "house_to_domain": {"1": "D1", "10": "D2", "2": "D3", "11": "D3", "7": "D4", "4": "D5", "5": "D6",
                        "6": "D7", "3": "D8", "9": "D9"},
    "unmapped_houses": [8, 12],
    "ziwei_palace_to_domain": {"命宫": "D1", "官禄": "D2", "财帛": "D3", "夫妻": "D4", "田宅": "D5", "子女": "D6",
                               "疾厄": "D7", "福德": "D9"},
    "ziwei_D8": "no palace mapped -> Sinic INSUFFICIENT for D8",
    "prominence": "score = occupants + (lord in kendra 1/4/7/10) + (lord strongly dignified); ZW: majors + transformations "
                  "+ six-lucky + six-malefic + body palace. high>=3, medium=2, low<=1",
    "polarity": "positive points: lord strong dignity, natural-benefic occupant (Jupiter, Venus); ZW: major star 庙/旺, "
                "禄/权/科, six-lucky, 禄存. negative points: lord debilitated/fall/detriment, lord in 6/8/12, lord combust "
                "(Jyotisha), natural-malefic occupant (J: Sun, Mars, Saturn, Rahu, Ketu; W: Mars, Saturn); ZW: major 陷, 忌, "
                "six-malefic. positive = pos>0 & neg=0; negative = neg>0 & pos=0; mixed = both; neutral = neither",
    "speaking": "cluster speaks on a domain when prominence is medium or high",
    "grade": "DIVERGENT if any two speaking clusters are positive vs negative; else STRONG if 3 speaking share polarity; "
             "MODERATE if 2 share polarity; WEAK if >=1 speaks without a shared pair; INSUFFICIENT if none speaks",
    "timing": {"jyotisha": "domains of houses ruled or occupied by current Mahadasha lord and Antardasha lord",
               "western": "profected house domain + domain of the house the lord of the year occupies natally",
               "sinic": "Zi Wei decadal palace domain + annual (流年) palace domain; BaZi luck/annual pillars annotated only"},
    "temperament": {
        "T1": {"jyotisha/western": "Sun", "ziwei_ming": ["紫微", "太阳", "天府"]},
        "T2": {"jyotisha/western": "Mars", "ziwei_ming": ["七杀", "破军", "贪狼"]},
        "T3": {"jyotisha/western": "Moon", "ziwei_ming": ["天同", "太阴", "天梁"]},
        "T4": {"jyotisha/western": "Mercury", "ziwei_ming": ["天机", "文昌", "文曲", "巨门"]},
        "T5": {"jyotisha/western": "3+ of 7 planets in dual/mutable signs", "ziwei_ming": ["天机", "天马"]},
        "T6": {"jyotisha/western": "Saturn", "ziwei_ming": ["天相", "武曲"]},
        "rule": "planet: + if in kendra/angular or strongly dignified (and not debilitated/fall/detriment); "
                "- if debilitated/fall/detriment and not angular; mixed if both; 0 otherwise. ZW: + if a listed star "
                "is in 命宫; 0 otherwise (absence is not contrary)"},
}
DOMAINS = {"D1": "Self/identity", "D2": "Career/status", "D3": "Wealth/gains", "D4": "Partnership",
           "D5": "Family/roots/home", "D6": "Children/creation", "D7": "Health/routine", "D8": "Mind/education/craft",
           "D9": "Fortune/spirituality/worldview"}
H2D = {int(k): v for k, v in REGISTRY["house_to_domain"].items()}
D2H = {}
for h, d in H2D.items():
    D2H.setdefault(d, []).append(h)


def level(score):
    return "high" if score >= 3 else "medium" if score == 2 else "low"


def polarity(pos, neg):
    return "positive" if pos and not neg else "negative" if neg and not pos else "mixed" if pos and neg else "neutral"


# ------------------------------------------------------------------ house-based cluster projections
def jy_project(j):
    g = j["grahas"]
    lag = SIGNS.index(j["lagna"]["sign"])
    out = {}
    for dom, hs in D2H.items():
        score = pos = neg = 0
        basis = []
        for h in hs:
            occ = [p for p, r in g.items() if r["house"] == h]
            lord = LORD[(lag + h - 1) % 12]
            lr = g[lord]
            strong = lr["dignity"] in ("exalted", "own", "moolatrikona")
            weak = lr["dignity"] == "debilitated"
            s = len(occ) + (lr["house"] in (1, 4, 7, 10)) + strong
            score = max(score, s)
            pos += strong + sum(p in ("Jupiter", "Venus") for p in occ)
            neg += weak + (lr["house"] in (6, 8, 12)) + bool(lr["combust"]) + \
                sum(p in ("Sun", "Mars", "Saturn", "Rahu", "Ketu") for p in occ)
            basis.append(f"H{h} {SIGNS[(lag + h - 1) % 12]}: occupants {occ or 'none'}; lord {lord} in H{lr['house']} "
                         f"{lr['sign']} ({lr['dignity']}{', combust' if lr['combust'] else ''})")
        out[dom] = dict(prominence=level(score), prominence_score=score, polarity=polarity(pos, neg), pos=pos, neg=neg,
                        basis="; ".join(basis))
    out["D8"]["basis"] += " [registry maps D8 to H3]"
    return out


def we_project(w):
    pl = w["planets"]
    lag = SIGNS.index(w["asc_sign"])
    out = {}
    for dom, hs in D2H.items():
        score = pos = neg = 0
        basis = []
        for h in hs:
            occ = [p for p, r in pl.items() if r["house"] == h]
            lord = LORD[(lag + h - 1) % 12]
            lr = pl[lord]
            dg = lr["dignities"]
            strong = ("domicile" in dg) or ("exaltation" in dg)
            weak = ("detriment" in dg) or ("fall" in dg)
            s = len(occ) + (lr["house"] in (1, 4, 7, 10)) + strong
            score = max(score, s)
            pos += strong + sum(p in ("Jupiter", "Venus") for p in occ)
            neg += weak + (lr["house"] in (6, 8, 12)) + sum(p in ("Mars", "Saturn") for p in occ)
            basis.append(f"H{h} {SIGNS[(lag + h - 1) % 12]}: occupants {occ or 'none'}; lord {lord} in H{lr['house']} "
                         f"{lr['sign']} ({', '.join(dg) or 'peregrine'})")
        out[dom] = dict(prominence=level(score), prominence_score=score, polarity=polarity(pos, neg), pos=pos, neg=neg,
                        basis="; ".join(basis))
    return out


LUCKY = {"左辅", "右弼", "文昌", "文曲", "天魁", "天钺"}
MALEFIC = {"擎羊", "陀罗", "火星", "铃星", "地空", "地劫"}


def zw_project(c):
    out = {}
    pal = {p["name"]: p for p in c["palaces"]}
    for name, dom in REGISTRY["ziwei_palace_to_domain"].items():
        p = pal[name]
        muts = [s["mutagen"] for s in p["major"] + p["minor"] if s["mutagen"]]
        luck = [s["name"] for s in p["minor"] if s["name"] in LUCKY]
        mal = [s["name"] for s in p["minor"] if s["name"] in MALEFIC]
        lucun = [s["name"] for s in p["minor"] if s["name"] == "禄存"]
        score = len(p["major"]) + len(muts) + len(luck) + len(mal) + bool(p["isBody"])
        pos = sum(s["brightness"] in ("庙", "旺") for s in p["major"]) + sum(m in ("禄", "权", "科") for m in muts) + \
            len(luck) + len(lucun)
        neg = sum(s["brightness"] == "陷" for s in p["major"]) + sum(m == "忌" for m in muts) + len(mal)
        basis = (f"{name} {p['stem']}{p['branch']}: majors {[(s['name'], s['brightness'], s['mutagen']) for s in p['major']] or 'none (empty palace)'}"
                 f"; lucky {luck or '-'}; malefic {mal or '-'}{'; 禄存' if lucun else ''}{'; body palace' if p['isBody'] else ''}")
        out[dom] = dict(prominence=level(score), prominence_score=score, polarity=polarity(pos, neg), pos=pos, neg=neg,
                        basis=basis)
    out["D8"] = dict(prominence="none", prominence_score=0, polarity="neutral", pos=0, neg=0,
                     basis="no Zi Wei palace mapped to D8 in MR-1")
    return out


def grade(projs):
    speak = {c: p for c, p in projs.items() if p["prominence"] in ("medium", "high")}
    pols = [p["polarity"] for p in speak.values()]
    if "positive" in pols and "negative" in pols:
        return "DIVERGENT", sorted(speak)
    if not speak:
        return "INSUFFICIENT", []
    best = max(set(pols), key=pols.count)
    n = pols.count(best)
    if n == 3:
        return "STRONG", sorted(speak)
    if n == 2:
        return "MODERATE", sorted(c for c, p in speak.items() if p["polarity"] == best)
    return "WEAK", sorted(speak)


# scenario pairing across the ensemble (Sinic primary track = apparent solar; civil alternative reported)
SCEN = {}
for k in ("T-unc", "T", "T+unc"):
    SCEN[k] = dict(jyotisha=jy_project(M["jyotisha"]["ensemble"][k]),
                   western=we_project(M["western"]["ensemble"][k]),
                   sinic=zw_project(M["ziwei"]["ensemble"][f"apparent_solar:{k}"]["chart"]))
SINIC_CIVIL_ALT = zw_project(M["ziwei"]["ensemble"]["civil:T+unc"]["chart"])

projections = []
domain_grades = {}
for d in DOMAINS:
    per = {}
    for k, s in SCEN.items():
        per[k] = grade({c: s[c][d] for c in ("jyotisha", "western", "sinic")})
    stable = len({json.dumps(v) for v in per.values()}) == 1
    domain_grades[d] = dict(name=DOMAINS[d], grade_at_T=per["T"][0], clusters_at_T=per["T"][1],
                            by_scenario={k: v[0] for k, v in per.items()}, stable=stable,
                            confidence=("medium" if stable else "low"))
    for c in ("jyotisha", "western", "sinic"):
        vals = {k: (SCEN[k][c][d]["prominence"], SCEN[k][c][d]["polarity"]) for k in SCEN}
        st = len(set(vals.values())) == 1
        projections.append(dict(domain=d, system=c if c != "sinic" else "ziwei", cluster=c,
                                prominence=SCEN["T"][c][d]["prominence"], polarity=SCEN["T"][c][d]["polarity"],
                                confidence=("unavailable" if SCEN["T"][c][d]["prominence"] == "none" else
                                            "medium" if st else "low"),
                                uncertainty_stability="stable" if st else "sensitive",
                                by_scenario={k: list(v) for k, v in vals.items()},
                                basis=SCEN["T"][c][d]["basis"], mapping_rule="MR-1"))

n_div = sum(1 for v in domain_grades.values() if v["grade_at_T"] == "DIVERGENT")
n_suff = sum(1 for v in domain_grades.values() if v["grade_at_T"] != "INSUFFICIENT")
divergence = dict(divergent=n_div, of_all_nine=f"{n_div}/9", of_sufficient=f"{n_div}/{n_suff}",
                  scenario_counts={k: sum(1 for v in domain_grades.values() if v["by_scenario"][k] == "DIVERGENT")
                                   for k in SCEN})

# BaZi internal annotation (not a vote)
B = M["bazi"]
tg = [B["ten_gods_visible"][p] for p in ("year", "month", "hour")] + [t[2] for p in B["hidden_stems"].values() for t in p]
fam = {"companion 比劫": ["比肩", "劫财"], "output 食伤": ["食神", "伤官"], "wealth 财": ["偏财", "正财"],
       "officer 官杀": ["七杀", "正官"], "resource 印": ["偏印", "正印"]}
bazi_annot = {k: sum(tg.count(x) for x in v) for k, v in fam.items()}


# ------------------------------------------------------------------ temperament
def planet_axis(cond_strong, cond_weak, kendra):
    if (kendra or cond_strong) and cond_weak:
        return "mixed"
    if kendra or cond_strong:
        return "+"
    if cond_weak:
        return "-"
    return "0"


def temperament(k):
    j = M["jyotisha"]["ensemble"][k]
    w = M["western"]["ensemble"][k]
    c = M["ziwei"]["ensemble"][f"apparent_solar:{k}"]["chart"]
    ming = next(p for p in c["palaces"] if p["name"] == "命宫")
    ming_stars = [s["name"] for s in ming["major"] + ming["minor"]]
    res = {}
    for ax, pl in (("T1", "Sun"), ("T2", "Mars"), ("T3", "Moon"), ("T4", "Mercury"), ("T6", "Saturn")):
        g = j["grahas"][pl]
        wp = w["planets"][pl]
        jv = planet_axis(g["dignity"] in ("exalted", "own", "moolatrikona"), g["dignity"] == "debilitated",
                         g["house"] in (1, 4, 7, 10))
        wv = planet_axis(bool({"domicile", "exaltation"} & set(wp["dignities"])),
                         bool({"detriment", "fall"} & set(wp["dignities"])), wp["angular"])
        stars = REGISTRY["temperament"][ax]["ziwei_ming"]
        sv = "+" if any(s in ming_stars for s in stars) else "0"
        res[ax] = dict(jyotisha=jv, jyotisha_basis=f"{pl} {g['sign']} H{g['house']} {g['dignity']}",
                       western=wv, western_basis=f"{pl} {wp['sign']} H{wp['house']} {wp['dignities'] or 'peregrine'}",
                       sinic=sv, sinic_basis=f"命宫 stars {ming_stars}")
    dual_j = sum(j["grahas"][p]["sign"] in ("Gemini", "Virgo", "Sagittarius", "Pisces") for p in
                 ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"))
    dual_w = sum(w["planets"][p]["sign"] in ("Gemini", "Virgo", "Sagittarius", "Pisces") for p in w["planets"])
    res["T5"] = dict(jyotisha="+" if dual_j >= 3 else "0", jyotisha_basis=f"{dual_j}/7 in dual signs",
                     western="+" if dual_w >= 3 else "0", western_basis=f"{dual_w}/7 in mutable signs",
                     sinic="+" if any(s in ming_stars for s in ("天机", "天马")) else "0",
                     sinic_basis=f"命宫 stars {ming_stars}")
    return res


TEMP = {k: temperament(k) for k in SCEN}


# ------------------------------------------------------------------ chronology
def d(s):
    return datetime.fromisoformat(s[:10]).date()


def jy_domains_for(lord, j):
    lag = SIGNS.index(j["lagna"]["sign"])
    hs = set()
    if lord in ("Rahu", "Ketu"):
        hs.add(j["grahas"][lord]["house"])
    else:
        hs |= {h for h in range(1, 13) if LORD[(lag + h - 1) % 12] == lord}
        hs.add(j["grahas"][lord]["house"])
    return sorted({H2D[h] for h in hs if h in H2D}), sorted(hs)


def chron(k):
    j = M["jyotisha"]["ensemble"][k]
    w = M["western"]["ensemble"][k]
    c = M["ziwei"]["ensemble"][f"apparent_solar:{k}"]["chart"]
    segs = []
    # jyotisha
    for md in M["jyotisha"]["vimshottari"][k]["mahadashas"]:
        for ad in md["antardashas"]:
            s, e = d(ad["start"]), d(ad["end"])
            if e < AS_OF or s > HORIZON:
                continue
            d1, h1 = jy_domains_for(md["lord"], j)
            d2, h2 = jy_domains_for(ad["lord"], j)
            segs.append(dict(cluster="jyotisha", start=s, end=e, domains=sorted(set(d1) | set(d2)),
                             label=f"{md['lord']} MD / {ad['lord']} AD (houses {sorted(set(h1) | set(h2))})"))
    # western profections (recomputed for scenario lagna)
    lag = SIGNS.index(w["asc_sign"])
    for y in range(AS_OF.year - 1, HORIZON.year + 1):
        age = y - BIRTH.year
        h = age % 12 + 1
        lord = LORD[(lag + h - 1) % 12]
        lh = w["planets"][lord]["house"]
        doms = sorted({H2D[x] for x in (h, lh) if x in H2D})
        s, e = BIRTH.replace(year=y), BIRTH.replace(year=y + 1)
        if e < AS_OF or s > HORIZON:
            continue
        segs.append(dict(cluster="western", start=s, end=e, domains=doms,
                         label=f"profection age {age}: H{h} {SIGNS[(lag + h - 1) % 12]}, lord of year {lord} natal H{lh}"))
    # sinic: decadal + yearly palaces, CNY boundaries
    from lunar_python import Lunar
    pal_by_branch = {p["branch"]: p for p in c["palaces"]}
    ZHI = "子丑寅卯辰巳午未申酉戌亥"
    for y in range(AS_OF.year - 1, HORIZON.year + 1):
        s = datetime.strptime(Lunar.fromYmd(y, 1, 1).getSolar().toYmd(), "%Y-%m-%d").date()
        e = datetime.strptime(Lunar.fromYmd(y + 1, 1, 1).getSolar().toYmd(), "%Y-%m-%d").date()
        if e < AS_OF or s > HORIZON:
            continue
        br = ZHI[(y - 4) % 12]
        yp = pal_by_branch[br]
        nominal = y - BIRTH.year + 1
        dp = next(p for p in c["palaces"] if p["decadal"][0] <= nominal <= p["decadal"][1])
        doms = sorted({x for x in (REGISTRY["ziwei_palace_to_domain"].get(dp["name"]),
                                   REGISTRY["ziwei_palace_to_domain"].get(yp["name"])) if x})
        segs.append(dict(cluster="sinic", start=s, end=e, domains=doms,
                         label=f"ZW decadal {dp['name']}({dp['branch']}) nominal age {nominal}; 流年 {br} -> natal {yp['name']}"))
    # overlaps
    cuts = sorted({AS_OF, HORIZON} | {x["start"] for x in segs if AS_OF < x["start"] < HORIZON} |
                  {x["end"] for x in segs if AS_OF < x["end"] < HORIZON})
    windows = []
    for a, b in zip(cuts, cuts[1:]):
        act = {}
        for sgm in segs:
            if sgm["start"] <= a and sgm["end"] >= b:
                for dm in sgm["domains"]:
                    act.setdefault(dm, set()).add(sgm["cluster"])
        for dm, cl in act.items():
            if len(cl) >= 2:
                windows.append(dict(domain=dm, start=a.isoformat(), end=b.isoformat(), clusters=sorted(cl),
                                    level="STRONG" if len(cl) == 3 else "MODERATE"))
    # merge contiguous same domain/cluster windows
    merged = []
    for wdw in sorted(windows, key=lambda x: (x["domain"], x["start"])):
        if merged and merged[-1]["domain"] == wdw["domain"] and merged[-1]["clusters"] == wdw["clusters"] and \
                merged[-1]["end"] == wdw["start"]:
            merged[-1]["end"] = wdw["end"]
        else:
            merged.append(dict(wdw))
    for x in segs:
        x["start"], x["end"] = x["start"].isoformat(), x["end"].isoformat()
    return dict(segments=segs, windows=sorted(merged, key=lambda x: x["start"]))


CHRON = {k: chron(k) for k in SCEN}
for wdw in CHRON["T"]["windows"]:
    a, b = d(wdw["start"]), d(wdw["end"])
    span = (a, b)
    present = []
    for k in SCEN:
        best = None
        for o in CHRON[k]["windows"]:
            if o["domain"] != wdw["domain"] or o["clusters"] != wdw["clusters"]:
                continue
            lo, hi = max(span[0], d(o["start"])), min(span[1], d(o["end"]))
            if lo < hi:
                best = (lo, hi)
        if best:
            present.append(k)
            span = best
    wdw["present_in_scenarios"] = present
    wdw["stable_span"] = [span[0].isoformat(), span[1].isoformat()] if len(present) == 3 else None
    wdw["confidence"] = "low" if len(present) < 3 else "medium"
    shared = []
    segs_T = [x for x in CHRON["T"]["segments"] if d(x["start"]) <= a and d(x["end"]) >= b]
    if "Jupiter" in " ".join(x["label"] for x in segs_T if x["cluster"] == "jyotisha") and \
            "Jupiter natal" in " ".join(x["label"] for x in segs_T if x["cluster"] == "western"):
        shared.append("Jyotisha and Western activations both run through Jupiter in Aries (same physical planet)")
    wdw["shared_basis_note"] = shared

# claim accounting
removed = dict(
    sensitive_projections_downgraded=sum(1 for p in projections if p["uncertainty_stability"] == "sensitive"),
    no_basis_unmapped=sum(1 for p in projections if p["confidence"] == "unavailable"),
    duplication_bazi_not_counted=len(bazi_annot),
    silent_low_prominence_not_counted_as_agreement=sum(1 for p in projections if p["prominence"] == "low"),
    maya_tibetan_meanings_excluded_no_attributed_source=2,
    timing_windows_not_stable_across_ensemble=sum(1 for w in CHRON["T"]["windows"] if w["confidence"] == "low"))

S = dict(registry=REGISTRY, domains=DOMAINS, projections=projections, domain_grades=domain_grades,
         divergence=divergence, bazi_internal_annotation=dict(ten_god_family_counts=bazi_annot,
                                                              note="internal Sinic corroboration only; not a vote"),
         sinic_civil_track_alternative_T_plus=dict((dm, (v["prominence"], v["polarity"])) for dm, v in SINIC_CIVIL_ALT.items()),
         temperament=TEMP, chronology=CHRON, claim_accounting=removed,
         overlays=dict(maya=dict(long_count=M["maya"]["long_count_str"], tzolkin=M["maya"]["tzolkin"],
                                 haab=M["maya"]["haab"], meaning="none used - no attributed Maya source in dataset"),
                       tibetan=dict(year=M["tibetan"]["element_animal"], meaning="none used - no sourced method computed")),
         independence_caveat="Jyotisha and Western are computed from the same sky positions; they differ in zodiac, "
                             "dignity and timing rules, but are not physically independent observations.")
json.dump(S, open(os.path.join(D, "SYNTHESIS.json"), "w"), ensure_ascii=False, indent=1, default=str)

for dm, v in domain_grades.items():
    print(dm, v["name"], v["grade_at_T"], v["clusters_at_T"], v["by_scenario"], v["stable"])
print(divergence)
for p in projections:
    print(p["domain"], p["cluster"], p["prominence"], p["polarity"], p["uncertainty_stability"], "|", p["basis"][:150])
print(json.dumps(TEMP["T"], ensure_ascii=False))
print(bazi_annot)
for k in SCEN:
    print("==", k)
    for wdw in CHRON[k]["windows"]:
        print(wdw)
for s in CHRON["T"]["segments"]:
    print(s)
print(removed)
