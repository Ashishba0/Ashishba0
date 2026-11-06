#!/usr/bin/env python3
"""Render INPUT_AUDIT.md, MASTER_DATASET.md, VERIFICATION_REPORT.md from the JSON outputs (facts only)."""
import json, os, sys

D = sys.argv[1]
M = json.load(open(os.path.join(D, "MASTER_DATASET.json")))
V = json.load(open(os.path.join(D, "VERIFICATION_REPORT.json")))
C = json.load(open(os.path.join(D, "CALCULATION_MANIFEST.json")))
A = M["input_audit"]


def f(x, n=4):
    return f"{x:.{n}f}" if isinstance(x, float) else str(x)


def dms(deg):
    d = int(deg)
    m = (deg - d) * 60
    return f"{d}°{int(m):02d}′{(m - int(m)) * 60:04.1f}″"


# ---------------------------------------------------------------- INPUT_AUDIT.md
L = ["# Input audit", "", "## Original input (unmodified)", ""]
L += [f"- **{k}**: {v}" for k, v in A["original"].items()]
L += ["", "## Normalized", "",
      f"| Field | Value |", "|---|---|",
      f"| Civil instant | {A['normalized_civil']} |", f"| IANA zone / tzdata | {A['iana_zone']} / {A['tzdata_release']} |",
      f"| UTC offset / DST | {A['utc_offset']} / {A['dst']} |", f"| UTC instant | {A['utc_instant']} |",
      f"| Weekday | {A['weekday']} |", f"| Latitude / longitude | {A['latitude']} / {A['longitude']} |",
      f"| Elevation | unavailable |", f"| Coordinate source | {A['coordinate_source']} |",
      f"| Local mean time | {A['local_mean_time']} |", f"| Equation of time | {A['equation_of_time_min']:.2f} min |",
      f"| Local apparent solar time | {A['local_apparent_solar_time']} |",
      f"| Sunrise / sunset (local) | {A['sunrise']} / {A['sunset']} |",
      f"| JD (UT) / ΔT | {A['jd_ut']:.6f} / {A['delta_t_sec']:.1f} s |",
      "", f"Historical offset: {A['historical_offset_note']}", "", f"Calendar: {A['calendar_conversion']}", "",
      "## Time-uncertainty ensemble", "",
      f"Stated certainty ±{json.load(open(os.path.join(D, 'BIRTH_INPUT.json')))['normalized']['uncertainty_minutes']} min → instants T−u, T, T+u (no rectification performed).", "",
      "## Boundary audit", "",
      "| Boundary | Value at T | Minutes to previous change | Minutes to next change | Inside ±30 min? |",
      "|---|---|---|---|---|"]
for k, v in M["boundaries"].items():
    p, n = v["minutes_to_previous_change"], v["minutes_to_next_change"]
    inside = any(isinstance(x, int) and x <= 30 for x in (p, n))
    L.append(f"| {k} | {v['value_at_T']} | {p} | {n} | {'**YES – sensitive**' if inside else 'no'} |")
L += ["", "Sign indices: 0=Aries … 11=Pisces; nakshatra index 0=Ashwini … 26=Revati.", "",
      "### What changes inside the interval", ""]
for sysname, key in (("Jyotisha", "jyotisha"), ("Western", "western")):
    for k, v in M[key]["sensitive_values"].items():
        L.append(f"- {sysname} `{k}`: " + ", ".join(f"{a}={b}" for a, b in v.items()))
for k, v in M["bazi"]["ensemble"].items():
    pass
L += ["- BaZi pillars per track/rule/instant: " + "; ".join(f"{k}: {v}" for k, v in M["bazi"]["ensemble"].items()),
      f"- Zi Wei track stability: {M['ziwei']['stability']}.",
      f"- Vimshottari dasha dates shift by {M['jyotisha']['vimshottari_shift_days_between_extremes']:.0f} days between T−u and T+u.",
      f"- Sect: {M['boundaries']['sect_sunset']['minutes_to_previous_change']}.",
      f"- Tibetan year boundary: {M['tibetan'].get('losar_boundary')}.",
      "- Gregorian/Julian: not applicable (modern Gregorian date)."]
open(os.path.join(D, "INPUT_AUDIT.md"), "w").write("\n".join(L) + "\n")

# ---------------------------------------------------------------- VERIFICATION_REPORT.md
L = ["# Verification report", "",
     "Engines: Swiss Ephemeris 2.10.03 (primary), Skyfield 1.55 + JPL DE421 (validator), lunar_python 1.4.9, "
     "iztro 2.5.0 (node) + py-iztro 0.1.5 (same method), convertdate 2.5.1 + own JDN arithmetic.", "",
     f"**Independence disclosure:** {C['independence_disclosure']}", "",
     f"**JPL kernel:** {C['jpl_kernel']['note']}", "",
     "| System | Datum | Primary | Validator | Difference | Stability | Confidence | Status |", "|---|---|---|---|---|---|---|---|"]
for r in V:
    pv = r["primary_value"]
    vv = r["validator_value"]
    L.append(f"| {r['system']} | {r['datum']} | {f(pv, 6) if isinstance(pv, float) else str(pv)[:70]} | "
             f"{(r['validator'] or '—')}: {f(vv, 6) if isinstance(vv, float) else str(vv)[:70]} | "
             f"{f(r['difference'], 6) if r['difference'] is not None else '—'} | {r['uncertainty_stability']} | "
             f"{r['confidence']} | {r['status']} |")
mx = max((r["difference"] for r in V if r["system"] == "shared" and "longitude" in r["datum"]), default=0)
L += ["", f"Largest planetary longitude difference: {mx:.2e}° (threshold 0.01°).",
      f"Alerts: {M['alerts'] or 'none'}. Failures: {[r['datum'] for r in V if r['status'] == 'fail'] or 'none'}.", "",
      "Boundary sensitivity of Lagna/Ascendant is listed in INPUT_AUDIT.md; numeric verification does not remove it.", "",
      "## Unavailable / excluded methods", ""] + [f"- {x}" for x in M["excluded_methods"]]
open(os.path.join(D, "VERIFICATION_REPORT.md"), "w").write("\n".join(L) + "\n")

# ---------------------------------------------------------------- MASTER_DATASET.md
J = M["jyotisha"]
jT = J["ensemble"]["T"]
L = ["# Master dataset (human-readable facts; no interpretation)", "", "## Conventions", ""]
L += [f"- **{k}**: {v}" for k, v in M["conventions"].items()]
L += ["", "## Jyotisha (sidereal, Lahiri, whole-sign) — at T", "",
      f"Lagna: {jT['lagna']['sign']} {dms(jT['lagna']['degree'])} ({jT['lagna']['nakshatra']} {jT['lagna']['pada']}); "
      f"T−30: {J['ensemble']['T-unc']['lagna']['sign']} {dms(J['ensemble']['T-unc']['lagna']['degree'])}; "
      f"T+30: {J['ensemble']['T+unc']['lagna']['sign']} {dms(J['ensemble']['T+unc']['lagna']['degree'])}", "",
      "| Graha | Sign | Degree | House (T) | Dignity | R | Combust | Nakshatra-pada | D9 | D10 |", "|---|---|---|---|---|---|---|---|---|---|"]
for p, r in jT["grahas"].items():
    L.append(f"| {p} | {r['sign']} | {dms(r['degree'])} | {r['house']} | {r['dignity']} | {'R' if r['retrograde'] else ''} | "
             f"{'yes' if r['combust'] else '' if r['combust'] is None else 'no'} | {r['nakshatra']} {r['pada']} | {r['d9']} | {r['d10']} |")
L += ["", f"Functional nature (T): {jT['functional_nature']}",
      f"Graha drishti (houses aspected, T): {jT['graha_drishti_houses']}",
      f"Planetary war: {jT['planetary_war'] or 'none'}; Rahu–Ketu separation {jT['rahu_ketu_separation']}°; "
      f"true node {jT['true_node']:.4f}°, mean node {jT['mean_node']:.4f}° (sidereal)",
      "", f"D9/D10 Lagna stability: {J['stability']['lagna_d9']}/{J['stability']['lagna_d10']} (sensitive → unavailable for reading).", "",
      "Whitelisted yogas (T): " + "; ".join(f"{y['name']} {y['placements']}" for y in J["yogas"]["T"]) +
      f" — yoga set stability: {J['yoga_stability']} (Raja-yoga lords change with Lagna).", "",
      "### Vimshottari (T; 365.25-day years)", "",
      f"Birth nakshatra lord {J['vimshottari']['T']['birth_nakshatra_lord']}, {J['vimshottari']['T']['fraction_elapsed'] * 100:.1f}% elapsed. "
      f"Boundary dates shift ±{J['vimshottari_shift_days_between_extremes'] / 2:.0f} days across the ±30 min interval.", "",
      "| Mahadasha | Start | End | T−30 start | T+30 start |", "|---|---|---|---|---|"]
for i, md in enumerate(J["vimshottari"]["T"]["mahadashas"]):
    L.append(f"| {md['lord']} | {md['start'][:10]} | {md['end'][:10]} | {J['vimshottari']['T-unc']['mahadashas'][i]['start'][:10]} | "
             f"{J['vimshottari']['T+unc']['mahadashas'][i]['start'][:10]} |")
rahu = next(m for m in J["vimshottari"]["T"]["mahadashas"] if m["lord"] == "Rahu")
L += ["", "Rahu Mahadasha antardashas (T):", ""] + [f"- {a['lord']}: {a['start'][:10]} → {a['end'][:10]}" for a in rahu["antardashas"]]
W = M["western"]
wT = W["ensemble"]["T"]
L += ["", "## Western / Hellenistic (tropical, whole-sign) — at T", "",
      f"Ascendant {wT['asc_sign']} {dms(wT['asc_degree'])} (T−30 {W['ensemble']['T-unc']['asc_sign']} {dms(W['ensemble']['T-unc']['asc_degree'])}; "
      f"T+30 {W['ensemble']['T+unc']['asc_sign']} {dms(W['ensemble']['T+unc']['asc_degree'])}); MC {wT['mc_sign']} (H{wT['mc_whole_sign_house']}); "
      f"sect {wT['sect']} (Sun altitude {wT['sun_altitude']:.1f}°)", "",
      "| Planet | Sign | Degree | House | Dignities | Sect status | R |", "|---|---|---|---|---|---|---|"]
for p, r in wT["planets"].items():
    L.append(f"| {p} | {r['sign']} | {dms(r['degree'])} | {r['house']} | {', '.join(r['dignities']) or 'peregrine'} | {r['sect_status']} | {'R' if r['retrograde'] else ''} |")
L += ["", f"Final dispositor: {wT['final_dispositors']}", "Aspects (≤6°): " +
      "; ".join(f"{a['a']} {a['aspect']} {a['b']} orb {a['orb']:.2f}° {'applying' if a['applying'] else 'separating'}" for a in wT["aspects"]),
      f"Lot of Fortune {wT['lot_fortune']['sign']} H{wT['lot_fortune']['house']} ({W['stability']['lot_fortune_sign']}); "
      f"Lot of Spirit {wT['lot_spirit']['sign']} H{wT['lot_spirit']['house']}",
      f"Optional modern track (no votes): {json.dumps(wT['optional_modern_track']['outer_planets'])}", "",
      "Profections: " + "; ".join(f"{p['start']}→{p['end']} age {p['age']} H{p['house']} {p['sign']} lord {p['lord_of_year']}" for p in W["profections"])]
B = M["bazi"]
L += ["", "## BaZi", "", f"Primary track: {B['primary_track']}", "",
      "| | Year | Month | Day | Hour |", "|---|---|---|---|---|",
      "| Pillar | " + " | ".join(B["pillars"][k] for k in ("year", "month", "day", "hour")) + " |",
      "| Ten God (stem) | " + " | ".join(B["ten_gods_visible"][k] for k in ("year", "month", "day", "hour")) + " |",
      "| Hidden stems | " + " | ".join(" ".join(f"{h[0]}({h[2]})" for h in B["hidden_stems"][k]) for k in ("year", "month", "day", "hour")) + " |",
      "| Na Yin (traditional attribute) | " + " | ".join(B["nayin"][k] for k in ("year", "month", "day", "hour")) + " |", "",
      f"Day Master {B['day_master']['stem']} ({B['day_master']['element']}, yang); month season {B['month_season']}; "
      f"seasonal state {B['day_master_seasonal_state']}; roots in branches: {B['strength']['roots'] or 'none'}; "
      f"support {B['strength']['support']:.2f} vs other {B['strength']['other']:.2f} → {B['strength']['classification']} "
      f"(rule set: {B['strength']['rule_set']})", "",
      f"Useful god: school {B['useful_god']['school']}; chain {B['useful_god']['rule_chain']}; favourable {B['useful_god']['favorable']}; "
      f"confidence {B['useful_god']['confidence']}. {B['useful_god']['other_schools']}", "",
      "Interactions: " + "; ".join(json.dumps(i, ensure_ascii=False) for i in B["interactions"]), "",
      f"Da Yun ({B['da_yun']['direction']}, {B['da_yun']['rule']}, {B['da_yun']['days_to_jie']:.2f} days to Jingzhe; "
      f"lunar_python start {B['da_yun']['lunar_python_start']}):", ""]
L += [f"- {p['pillar']} {p['start'][:10]} → {p['end'][:10]} (stem {p['stem_ten_god']}, branch main {p['branch_main_ten_god']})" for p in B["da_yun"]["periods"][:5]]
L += ["", "Annual pillars (Lichun to Lichun): " + "; ".join(f"{a['year_pillar']} {a['start'][:10]} ({a['stem_ten_god']}/{a['branch_main_ten_god']})" for a in B["annual_pillars"])]
Z = M["ziwei"]["ensemble"]["apparent_solar:T"]["chart"]
L += ["", "## Zi Wei Dou Shu (iztro 2.5.0, apparent-solar track)", "",
      f"Solar {Z['solarDate']}; lunar {Z['lunarDate']} (no leap month); time {Z['time']} {Z['timeRange']}; "
      f"Five-Elements Bureau {Z['fiveElementsClass']}; Ming palace {Z['soulBranch']}, Shen palace {Z['bodyBranch']}; "
      f"life ruler {Z['soul']}, body ruler {Z['body']}. Four Transformations source: year stem 庚.", "",
      "| Palace | Stem-Branch | Major stars (brightness, 化) | Minor (declared set) | Decadal (nominal age) |", "|---|---|---|---|---|"]
for p in Z["palaces"]:
    L.append(f"| {p['name']}{' (身)' if p['isBody'] else ''} | {p['stem']}{p['branch']} | "
             f"{', '.join(s['name'] + '(' + (s['brightness'] or '') + (',' + s['mutagen'] if s['mutagen'] else '') + ')' for s in p['major']) or '—'} | "
             f"{', '.join(s['name'] for s in p['minor']) or '—'} | {p['decadal'][0]}–{p['decadal'][1]} |")
L += ["", f"As of 2026-11-06: {Z['horoscope_asof']}",
      f"Track stability: {M['ziwei']['stability']} – alternatives in MASTER_DATASET.json."]
Mx = M["maya"]
L += ["", "## Maya calendar (GMT 584283)", "",
      f"Long Count {Mx['long_count_str']}; Tzolkʼin {Mx['tzolkin']['number']} {Mx['tzolkin']['name']}; "
      f"Haabʼ {Mx['haab']['day']} {Mx['haab']['month']}; round-trip {Mx['roundtrip']}. {Mx['day_convention']}.",
      "", "## Tibetan", "", f"{M['tibetan']['element_animal']} ({M['tibetan']['source']}); Losar: {M['tibetan']['losar_boundary']}. "
      f"Mewa: {M['tibetan']['mewa']}. Parkha: {M['tibetan']['parkha']}. Personal forces: {M['tibetan']['personal_forces']}.",
      "", "## Excluded methods", ""] + [f"- {x}" for x in M["excluded_methods"]]
open(os.path.join(D, "MASTER_DATASET.md"), "w").write("\n".join(L) + "\n")
print("rendered")
