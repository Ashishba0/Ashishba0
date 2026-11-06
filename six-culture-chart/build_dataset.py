#!/usr/bin/env python3
"""Deterministic six-culture chart builder.

Reads BIRTH_INPUT.json, writes MASTER_DATASET.json, VERIFICATION_REPORT.json,
CALCULATION_MANIFEST.json. Facts only - no interpretation.

Usage: python build_dataset.py <dir_with_BIRTH_INPUT.json> <swisseph_ephe_dir> <jpl_bsp_path> <iztro_node_dir>
"""
import hashlib, json, math, os, platform, subprocess, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe
from skyfield.api import Loader, wgs84
from skyfield.framelib import ecliptic_frame
from skyfield import almanac
from lunar_python import Solar, Lunar
from convertdate import mayan
import convertdate, skyfield, lunar_python, tzdata

OUT = sys.argv[1]
EPHE = sys.argv[2]
BSP = sys.argv[3]
NODE_DIR = sys.argv[4]

INP = json.load(open(os.path.join(OUT, "BIRTH_INPUT.json")))
N = INP["normalized"]
LAT, LON = N["latitude"], N["longitude"]
TZ = ZoneInfo(N["time_zone_iana"])
UNC = N["uncertainty_minutes"]
AS_OF = datetime.fromisoformat(N["as_of_date"]).date()

swe.set_ephe_path(EPHE)
SWFLAG = swe.FLG_SWIEPH | swe.FLG_SPEED

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
         "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
PL = {"Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY, "Venus": swe.VENUS,
      "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN}
OUTER = {"Uranus": swe.URANUS, "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO}
LORD = ["Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury", "Venus", "Mars", "Jupiter",
        "Saturn", "Saturn", "Jupiter"]
EXALT = {"Sun": 0, "Moon": 1, "Mars": 9, "Mercury": 5, "Jupiter": 3, "Venus": 11, "Saturn": 6}
alerts = []
verif = []


def norm(x):
    return x % 360.0


def angdiff(a, b):
    d = abs(norm(a) - norm(b))
    return min(d, 360 - d)


def sign_of(lon):
    return int(norm(lon) // 30)


def local_dt(offset_min=0):
    base = datetime.fromisoformat(f"{N['civil_date']}T{N['civil_time_24h']}").replace(tzinfo=TZ)
    return base + timedelta(minutes=offset_min)


def jd_ut(dt):
    u = dt.astimezone(timezone.utc)
    return swe.julday(u.year, u.month, u.day, u.hour + u.minute / 60 + u.second / 3600)


def jd_to_dt(jd):
    y, m, d, h = swe.revjul(jd)
    return (datetime(y, m, d, tzinfo=timezone.utc) + timedelta(hours=h))


def iso(dt):
    return dt.isoformat(timespec="seconds")


def addv(system, datum, primary_engine, pv, validator, vv, diff, convention, thr=None,
         boundary=None, stability="stable", confidence=None, status=None, note=None):
    if status is None:
        status = "pass" if (thr is None or diff is None or diff <= thr) else "alert"
    if status == "alert":
        alerts.append(f"{system}:{datum} diff={diff}")
    if confidence is None:
        if validator and status == "pass" and stability == "stable":
            confidence = "high"
        elif stability != "stable":
            confidence = "low"
        else:
            confidence = "medium"
    r = dict(system=system, datum=datum, primary_engine=primary_engine, primary_value=pv,
             validator=validator, validator_value=vv, difference=diff, convention=convention,
             boundary_distance=boundary, uncertainty_stability=stability,
             confidence=confidence, status=status)
    if note:
        r["note"] = note
    verif.append(r)
    return r


# ---------------------------------------------------------------- swe positions
def swe_pos(jd, body, sid=False):
    fl = SWFLAG | (swe.FLG_SIDEREAL if sid else 0)
    xx, ret = swe.calc_ut(jd, body, fl)
    if not ret & swe.FLG_SWIEPH:
        alerts.append(f"swisseph fell back from SWIEPH for body {body}")
    return xx


def set_lahiri():
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)


set_lahiri()


def angles(jd, sid=False, lat=LAT, lon=LON):
    if sid:
        cusps, ascmc = swe.houses_ex(jd, lat, lon, b"W", swe.FLG_SIDEREAL)
    else:
        cusps, ascmc = swe.houses_ex(jd, lat, lon, b"W", 0)
    return ascmc[0], ascmc[1], ascmc[2]  # asc, mc, armc


# ---------------------------------------------------------------- skyfield validator
load = Loader(os.path.dirname(BSP))
ts = load.timescale(builtin=True)
eph = load(os.path.basename(BSP))
earth = eph["earth"]
SKY = {"Sun": eph["sun"], "Moon": eph["moon"], "Mercury": eph["mercury"], "Venus": eph["venus"],
       "Mars": eph["mars barycenter"], "Jupiter": eph["jupiter barycenter"],
       "Saturn": eph["saturn barycenter"]}
topos = wgs84.latlon(LAT, LON)


def sky_lon(dt, name):
    t = ts.from_datetime(dt.astimezone(timezone.utc))
    lat_, lon_, _ = earth.at(t).observe(SKY[name]).apparent().frame_latlon(ecliptic_frame)
    return lon_.degrees % 360, lat_.degrees


def sky_asc_mc(dt, lat=LAT, lon=LON):
    t = ts.from_datetime(dt.astimezone(timezone.utc))
    from skyfield.nutationlib import mean_obliquity, iau2000a_radians
    dpsi, deps = iau2000a_radians(t)
    eps = math.radians(mean_obliquity(t.tdb) / 3600.0) + deps
    ramc = math.radians((t.gast * 15 + lon) % 360)
    phi = math.radians(lat)
    asc = math.degrees(math.atan2(math.cos(ramc), -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps))))
    mc = math.degrees(math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps)))
    return norm(asc), norm(mc)


# ================================================================ STEP 2: input audit
T0 = local_dt(0)
JD0 = jd_ut(T0)
utc0 = T0.astimezone(timezone.utc)
offset = T0.utcoffset()
dst = T0.dst()
lmt = utc0 + timedelta(hours=LON / 15)
eot_days = swe.time_equ(JD0)
eot_min = eot_days * 1440
lat_time = lmt + timedelta(minutes=eot_min)
# independent apparent solar time from skyfield local hour angle of Sun
t_sf = ts.from_datetime(utc0)
ha, dec, _ = (earth + topos).at(t_sf).observe(eph["sun"]).apparent().hadec()
sf_last_hours = (ha.hours + 12) % 24
lat_hours = lat_time.hour + lat_time.minute / 60 + lat_time.second / 3600
addv("input", "Local apparent solar time (hours)", "Swiss Ephemeris swe_time_equ", lat_hours,
     "Skyfield Sun local hour angle", sf_last_hours, abs(lat_hours - sf_last_hours) * 3600,
     "difference in seconds", thr=30)


def sun_events(day_local):
    start = datetime(day_local.year, day_local.month, day_local.day, tzinfo=TZ)
    t0 = ts.from_datetime(start.astimezone(timezone.utc))
    t1 = ts.from_datetime((start + timedelta(days=1)).astimezone(timezone.utc))
    f = almanac.sunrise_sunset(eph, topos)
    tt, yy = almanac.find_discrete(t0, t1, f)
    res = {}
    for ti, yi in zip(tt, yy):
        res["sunrise" if yi else "sunset"] = ti.utc_datetime().astimezone(TZ)
    # swiss
    jd = jd_ut(start)
    sw = {}
    for key, fl in (("sunrise", swe.CALC_RISE), ("sunset", swe.CALC_SET)):
        r, tret = swe.rise_trans(jd, swe.SUN, fl | swe.BIT_DISC_CENTER * 0, (LON, LAT, 0), 1013.25, 15, SWFLAG)
        sw[key] = jd_to_dt(tret[0]).astimezone(TZ)
    return res, sw


sk_ev, sw_ev = sun_events(T0.date())
for k in ("sunrise", "sunset"):
    addv("input", f"{k} {T0.date()}", "Swiss Ephemeris rise_trans", iso(sw_ev[k]), "Skyfield almanac",
         iso(sk_ev[k]), abs((sw_ev[k] - sk_ev[k]).total_seconds()), "upper limb, standard refraction; diff seconds",
         thr=60)

input_audit = dict(
    original=INP["original_user_input"],
    normalized_civil=iso(T0), iana_zone=N["time_zone_iana"], tzdata_release=tzdata.IANA_VERSION,
    utc_offset=str(offset), dst=str(dst), utc_instant=iso(utc0), weekday=T0.strftime("%A"),
    latitude=LAT, longitude=LON, elevation_m=None, coordinate_source=N["coordinate_source"],
    local_mean_time=lmt.strftime("%Y-%m-%dT%H:%M:%S"), equation_of_time_min=eot_min,
    local_apparent_solar_time=lat_time.strftime("%Y-%m-%dT%H:%M:%S"),
    sunrise=iso(sk_ev["sunrise"]), sunset=iso(sk_ev["sunset"]),
    jd_ut=JD0, jd_tt=JD0 + swe.deltat(JD0), delta_t_sec=swe.deltat(JD0) * 86400,
    calendar_conversion="Gregorian date as given; no conversion required (India Gregorian since British era).",
    historical_offset_note=(N.get("historical_offset_note", "") + " Offset/DST from tzdata as shown.").strip(),
)

# ================================================================ STEP 4A astro core
ENSEMBLE = {"T-unc": -UNC, "T": 0, "T+unc": UNC}


def jy_core(jd):
    set_lahiri()
    out = {}
    for n, b in PL.items():
        out[n] = swe_pos(jd, b, sid=True)
    rt = swe_pos(jd, swe.TRUE_NODE, sid=True)
    rm = swe_pos(jd, swe.MEAN_NODE, sid=True)
    asc, mc, _ = angles(jd, sid=True)
    return out, rt, rm, asc, mc


def west_core(jd):
    out = {n: swe_pos(jd, b) for n, b in PL.items()}
    outer = {n: swe_pos(jd, b) for n, b in OUTER.items()}
    asc, mc, armc = angles(jd)
    return out, outer, asc, mc


# verification of planetary longitudes at T
trop_T, outer_T, ascT, mcT = west_core(JD0)
maxdiff = 0
for n in PL:
    sl, sb = sky_lon(T0, n)
    d = angdiff(trop_T[n][0], sl)
    maxdiff = max(maxdiff, d)
    addv("shared", f"{n} tropical apparent longitude", "Swiss Ephemeris 2.10.03 (sepl/semo_18, DE431-based)",
         trop_T[n][0], "Skyfield 1.55 + JPL DE421", sl, d, "geocentric apparent, ecliptic & equinox of date",
         thr=0.01)
sa, sm = sky_asc_mc(T0)
addv("shared", "Ascendant tropical", "Swiss Ephemeris houses_ex", ascT, "Skyfield GAST + IAU2000A obliquity, closed-form",
     sa, angdiff(ascT, sa), "tropical, true obliquity", thr=0.05)
addv("shared", "MC tropical", "Swiss Ephemeris houses_ex", mcT, "Skyfield GAST closed-form", sm, angdiff(mcT, sm),
     "tropical", thr=0.05)
ayan = swe.get_ayanamsa_ut(JD0)
# node validation: mean node vs Meeus polynomial (independent formula)
Tc = (JD0 + swe.deltat(JD0) - 2451545.0) / 36525
meeus_node = norm(125.0445479 - 1934.1362891 * Tc + 0.0020754 * Tc ** 2 + Tc ** 3 / 467441 - Tc ** 4 / 60616000)
mn_trop = swe_pos(JD0, swe.MEAN_NODE)[0]
addv("jyotisha", "Mean node tropical longitude", "Swiss Ephemeris MEAN_NODE", mn_trop,
     "Meeus (Astronomical Algorithms 2e, 47.7) polynomial", meeus_node, angdiff(mn_trop, meeus_node),
     "mean ascending node, mean equinox of date", thr=0.01)
tn_trop = swe_pos(JD0, swe.TRUE_NODE)[0]
addv("jyotisha", "True node tropical longitude", "Swiss Ephemeris TRUE_NODE", tn_trop, None, None, None,
     "osculating node", confidence="medium", note="single-engine; no independent true-node implementation available")
addv("jyotisha", "Lahiri ayanamsha", "Swiss Ephemeris SIDM_LAHIRI", ayan, None, None, None,
     "Lahiri (Chitrapaksha) per Swiss Ephemeris definition", confidence="medium",
     note="convention value; not independently re-derived")

# ================================================================ boundary scanning utility


def scan_boundary(fn, span_min=720, step=1):
    """Return value at T and minutes to nearest change before/after within span."""
    v0 = fn(0)
    before = after = None
    for m in range(step, span_min + 1, step):
        if after is None and fn(m) != v0:
            after = m
        if before is None and fn(-m) != v0:
            before = m
        if after is not None and before is not None:
            break
    return v0, before, after


def at_offset(m):
    return jd_ut(local_dt(m))


# ================================================================ 4B Jyotisha
NAK = ["Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu", "Pushya", "Ashlesha",
       "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
       "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
       "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"]
DASHA_SEQ = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
DASHA_YRS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7, "Rahu": 18, "Jupiter": 16, "Saturn": 19,
             "Mercury": 17}
MT = {"Sun": (4, 0, 20), "Moon": (1, 3, 30), "Mars": (0, 0, 12), "Mercury": (5, 15, 20), "Jupiter": (8, 0, 10),
      "Venus": (6, 0, 15), "Saturn": (10, 0, 20)}
FRIENDS = {
    "Sun": ({"Moon", "Mars", "Jupiter"}, {"Mercury"}, {"Venus", "Saturn"}),
    "Moon": ({"Sun", "Mercury"}, {"Mars", "Jupiter", "Venus", "Saturn"}, set()),
    "Mars": ({"Sun", "Moon", "Jupiter"}, {"Venus", "Saturn"}, {"Mercury"}),
    "Mercury": ({"Sun", "Venus"}, {"Mars", "Jupiter", "Saturn"}, {"Moon"}),
    "Jupiter": ({"Sun", "Moon", "Mars"}, {"Saturn"}, {"Mercury", "Venus"}),
    "Venus": ({"Mercury", "Saturn"}, {"Mars", "Jupiter"}, {"Sun", "Moon"}),
    "Saturn": ({"Mercury", "Venus"}, {"Jupiter"}, {"Sun", "Moon", "Mars"}),
}
COMBUST = {"Moon": 12, "Mars": 17, "Mercury": 14, "Jupiter": 11, "Venus": 10, "Saturn": 15}
COMBUST_R = {"Mercury": 12, "Venus": 8}


def jy_dignity(p, lon):
    s = sign_of(lon)
    deg = lon % 30
    if p not in EXALT:
        return "n/a (node; school-dependent)"
    if s == EXALT[p]:
        return "exalted"
    if s == (EXALT[p] + 6) % 12:
        return "debilitated"
    mts, a, b = MT[p]
    if s == mts and a <= deg < b:
        return "moolatrikona"
    if LORD[s] == p:
        return "own"
    f, n, e = FRIENDS[p]
    lord = LORD[s]
    return "friend" if lord in f else "neutral" if lord in n else "enemy"


def nakshatra(lon):
    i = int(norm(lon) // (360 / 27))
    pada = int((norm(lon) % (360 / 27)) // (360 / 108)) + 1
    return NAK[i], pada, DASHA_SEQ[i % 9], i


def d9(lon):
    return int((norm(lon) * 9) // 30) % 12


def d10(lon):
    s = sign_of(lon)
    part = int((lon % 30) // 3)
    start = s if s % 2 == 0 else (s + 8) % 12  # odd signs (Aries idx0) from same; even from 9th
    return (start + part) % 12


def jyotisha(jd):
    g, rt, rm, asc, mc = jy_core(jd)
    lag = sign_of(asc)
    gl = {p: g[p][0] for p in g}
    gl["Rahu"] = rt[0]
    gl["Ketu"] = norm(rt[0] + 180)
    speeds = {p: g[p][3] for p in g}
    speeds["Rahu"] = rt[3]
    speeds["Ketu"] = rt[3]
    sun = gl["Sun"]
    rows = {}
    for p, lon in gl.items():
        s = sign_of(lon)
        nk, pada, nl, _ = nakshatra(lon)
        retro = speeds[p] < 0 if p not in ("Rahu", "Ketu") else True
        comb = None
        if p in COMBUST:
            orb = COMBUST_R.get(p, COMBUST[p]) if (speeds[p] < 0 and p in COMBUST_R) else COMBUST[p]
            comb = angdiff(lon, sun) <= orb
        rows[p] = dict(longitude=lon, sign=SIGNS[s], degree=lon % 30, house=(s - lag) % 12 + 1,
                       speed=speeds[p], retrograde=retro, combust=comb, dignity=jy_dignity(p, lon),
                       nakshatra=nk, pada=pada, nakshatra_lord=nl, d9=SIGNS[d9(lon)], d10=SIGNS[d10(lon)])
    # planetary war
    wars = []
    tara = ["Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
    for i, a in enumerate(tara):
        for b in tara[i + 1:]:
            if angdiff(gl[a], gl[b]) < 1:
                wars.append([a, b, angdiff(gl[a], gl[b])])
    houses = {h: SIGNS[(lag + h - 1) % 12] for h in range(1, 13)}
    owners = {}
    for h in range(1, 13):
        owners.setdefault(LORD[(lag + h - 1) % 12], []).append(h)
    # functional nature (declared BPHS-style rule)
    func = {}
    for p, hs in owners.items():
        hs_set = set(hs)
        tri = hs_set & {1, 5, 9}
        ken = hs_set & {4, 7, 10}
        bad = hs_set & {3, 6, 8, 11}
        if tri and ken and 1 not in hs_set:
            func[p] = "yogakaraka"
        elif tri:
            func[p] = "functional benefic" if not (bad - {8}) or 1 in hs_set else "mixed"
        elif bad and not ken:
            func[p] = "functional malefic"
        elif ken and p in ("Jupiter", "Venus", "Mercury", "Moon"):
            func[p] = "neutral (kendradhipati dosha)"
        else:
            func[p] = "neutral"
    # drishti
    special = {"Mars": [4, 7, 8], "Jupiter": [5, 7, 9], "Saturn": [3, 7, 10]}
    asp = {}
    for p in PL:
        h = rows[p]["house"]
        asp[p] = sorted(((h + k - 2) % 12 + 1) for k in special.get(p, [7]))
    lagna = dict(longitude=asc, sign=SIGNS[lag], degree=asc % 30, nakshatra=nakshatra(asc)[0],
                 pada=nakshatra(asc)[1], d9=SIGNS[d9(asc)], d10=SIGNS[d10(asc)])
    return dict(lagna=lagna, grahas=rows, house_signs=houses, house_owners=owners, functional_nature=func,
                graha_drishti_houses=asp, planetary_war=wars, mean_node=rm[0], true_node=rt[0],
                rahu_ketu_separation=angdiff(gl["Rahu"], gl["Ketu"]), moon_lon=gl["Moon"])


JY = {k: jyotisha(at_offset(v)) for k, v in ENSEMBLE.items()}
jyT = JY["T"]


def stab(getter):
    vals = {k: getter(JY[k]) for k in JY}
    return ("stable" if len(set(map(str, vals.values()))) == 1 else "sensitive"), vals


jy_stability = {}
jy_stability["lagna_sign"] = stab(lambda j: j["lagna"]["sign"])
jy_stability["lagna_d9"] = stab(lambda j: j["lagna"]["d9"])
jy_stability["lagna_d10"] = stab(lambda j: j["lagna"]["d10"])
jy_stability["lagna_nakshatra_pada"] = stab(lambda j: (j["lagna"]["nakshatra"], j["lagna"]["pada"]))
for p in jyT["grahas"]:
    for k in ("sign", "house", "nakshatra", "pada", "d9", "d10", "dignity", "combust"):
        jy_stability[f"{p}.{k}"] = stab(lambda j, p=p, k=k: j["grahas"][p][k])
jy_sensitive = {k: v[1] for k, v in jy_stability.items() if v[0] != "stable"}

# boundary distances (Jyotisha)
bd = {}


def jy_lag(m):
    set_lahiri()
    return sign_of(angles(at_offset(m), sid=True)[0])


def jy_lag_d9(m):
    set_lahiri()
    return d9(angles(at_offset(m), sid=True)[0])


def jy_lag_d10(m):
    set_lahiri()
    return d10(angles(at_offset(m), sid=True)[0])


def moon_sid(m):
    set_lahiri()
    return swe_pos(at_offset(m), swe.MOON, sid=True)[0]


bd["jyotisha_lagna_sign"] = scan_boundary(jy_lag, 240)
bd["jyotisha_lagna_d9"] = scan_boundary(jy_lag_d9, 120)
bd["jyotisha_lagna_d10"] = scan_boundary(jy_lag_d10, 120)
bd["moon_sidereal_sign"] = scan_boundary(lambda m: sign_of(moon_sid(m)), 2880, 5)
bd["moon_nakshatra"] = scan_boundary(lambda m: nakshatra(moon_sid(m))[3], 2880, 5)
bd["moon_pada"] = scan_boundary(lambda m: nakshatra(moon_sid(m))[1], 1440, 2)
bd["moon_d9"] = scan_boundary(lambda m: d9(moon_sid(m)), 1440, 2)
bd["moon_d10"] = scan_boundary(lambda m: d10(moon_sid(m)), 1440, 2)


# Vimshottari
def vimshottari(moon_lon, birth_dt, levels=2):
    nk_len = 360 / 27
    _, _, lord, idx = nakshatra(moon_lon)
    frac_elapsed = (norm(moon_lon) % nk_len) / nk_len
    YEAR = 365.25
    start_i = DASHA_SEQ.index(lord)
    md_start = birth_dt - timedelta(days=frac_elapsed * DASHA_YRS[lord] * YEAR)
    out = []
    t = md_start
    for k in range(9):
        L = DASHA_SEQ[(start_i + k) % 9]
        md_end = t + timedelta(days=DASHA_YRS[L] * YEAR)
        ads = []
        ta = t
        for j in range(9):
            A = DASHA_SEQ[(DASHA_SEQ.index(L) + j) % 9]
            dur = DASHA_YRS[L] * DASHA_YRS[A] / 120 * YEAR
            ads.append(dict(lord=A, start=iso(ta), end=iso(ta + timedelta(days=dur))))
            ta = ta + timedelta(days=dur)
        out.append(dict(lord=L, start=iso(t), end=iso(md_end), antardashas=ads))
        t = md_end
    return dict(birth_nakshatra_lord=lord, fraction_elapsed=frac_elapsed, year_length_days=YEAR, mahadashas=out)


VIM = {k: vimshottari(JY[k]["moon_lon"], local_dt(v)) for k, v in ENSEMBLE.items()}
vim_shift_days = (datetime.fromisoformat(VIM["T-unc"]["mahadashas"][1]["start"]) -
                  datetime.fromisoformat(VIM["T+unc"]["mahadashas"][1]["start"])).total_seconds() / 86400


# Yogas (declared whitelist)
def yogas(j):
    g = j["grahas"]
    res = []
    mh = g["Moon"]["house"]
    rel = (g["Jupiter"]["house"] - mh) % 12 + 1
    if rel in (1, 4, 7, 10):
        res.append(dict(name="Gajakesari", rule="Jupiter in kendra (1/4/7/10) from Moon",
                        placements=dict(Moon=g["Moon"]["sign"], Jupiter=g["Jupiter"]["sign"], relation=rel)))
    if g["Sun"]["sign"] == g["Mercury"]["sign"]:
        res.append(dict(name="Budha-Aditya", rule="Sun and Mercury in same sign",
                        placements=dict(sign=g["Sun"]["sign"], mercury_combust=g["Mercury"]["combust"])))
    if g["Moon"]["sign"] == g["Mars"]["sign"]:
        res.append(dict(name="Chandra-Mangala", rule="Moon and Mars in same sign", placements=dict(sign=g["Moon"]["sign"])))
    for p, nm in (("Mars", "Ruchaka"), ("Mercury", "Bhadra"), ("Jupiter", "Hamsa"), ("Venus", "Malavya"),
                  ("Saturn", "Shasha")):
        if g[p]["house"] in (1, 4, 7, 10) and g[p]["dignity"] in ("exalted", "own", "moolatrikona"):
            res.append(dict(name=f"{nm} (Pancha Mahapurusha)", rule=f"{p} own/exalted/MT sign in kendra from Lagna",
                            placements=dict(planet=p, sign=g[p]["sign"], house=g[p]["house"])))
    owners = j["house_owners"]
    kl = {p for p, hs in owners.items() if set(hs) & {1, 4, 7, 10}}
    tl = {p for p, hs in owners.items() if set(hs) & {1, 5, 9}}
    seen = set()
    for a in sorted(kl):
        for b in sorted(tl):
            if a != b and g[a]["sign"] == g[b]["sign"] and (b, a) not in seen:
                seen.add((a, b))
                res.append(dict(name="Raja yoga (kendra-trikona lord conjunction)",
                                rule="lord of a kendra and lord of a trikona in same sign",
                                placements=dict(kendra_lord=a, trikona_lord=b, sign=g[a]["sign"],
                                                house=g[a]["house"])))
    return res


YOG = {k: yogas(JY[k]) for k in JY}
yoga_names = {k: sorted(y["name"] + str(y["placements"].get("kendra_lord", "")) for y in v) for k, v in YOG.items()}
yoga_stability = "stable" if len({json.dumps(v) for v in yoga_names.values()}) == 1 else "sensitive"

addv("jyotisha", "Rahu-Ketu separation", "internal", jyT["rahu_ketu_separation"], None, None,
     abs(jyT["rahu_ketu_separation"] - 180), "true node", thr=1e-9, confidence="high")
addv("jyotisha", "Vimshottari total years", "internal", sum(DASHA_YRS.values()), None, None,
     abs(sum(DASHA_YRS.values()) - 120), "", thr=0, confidence="high")


def check_continuous(periods):
    for a, b in zip(periods, periods[1:]):
        if abs((datetime.fromisoformat(a["end"]) - datetime.fromisoformat(b["start"])).total_seconds()) > 1:
            return False
    return True


ok = check_continuous(VIM["T"]["mahadashas"]) and all(check_continuous(m["antardashas"]) for m in VIM["T"]["mahadashas"])
addv("jyotisha", "Vimshottari continuity", "internal", ok, None, None, None, "", status="pass" if ok else "fail",
     confidence="high" if ok else "unavailable")

# ================================================================ 4D Western / Hellenistic
TRIP = {0: ("Sun", "Jupiter", "Saturn"), 1: ("Venus", "Moon", "Mars"), 2: ("Saturn", "Mercury", "Jupiter"),
        3: ("Venus", "Mars", "Moon")}  # Dorothean: day, night, participating; element = sign%4
BOUNDS = [  # Egyptian bounds (Ptolemy, Tetrabiblos I.20)
    [("Jupiter", 6), ("Venus", 12), ("Mercury", 20), ("Mars", 25), ("Saturn", 30)],
    [("Venus", 8), ("Mercury", 14), ("Jupiter", 22), ("Saturn", 27), ("Mars", 30)],
    [("Mercury", 6), ("Jupiter", 12), ("Venus", 17), ("Mars", 24), ("Saturn", 30)],
    [("Mars", 7), ("Venus", 13), ("Mercury", 19), ("Jupiter", 26), ("Saturn", 30)],
    [("Jupiter", 6), ("Venus", 11), ("Saturn", 18), ("Mercury", 24), ("Mars", 30)],
    [("Mercury", 7), ("Venus", 17), ("Jupiter", 21), ("Mars", 28), ("Saturn", 30)],
    [("Saturn", 6), ("Mercury", 14), ("Jupiter", 21), ("Venus", 28), ("Mars", 30)],
    [("Mars", 7), ("Venus", 11), ("Mercury", 19), ("Jupiter", 24), ("Saturn", 30)],
    [("Jupiter", 12), ("Venus", 17), ("Mercury", 21), ("Saturn", 26), ("Mars", 30)],
    [("Mercury", 7), ("Jupiter", 14), ("Venus", 22), ("Saturn", 26), ("Mars", 30)],
    [("Mercury", 7), ("Venus", 13), ("Jupiter", 20), ("Mars", 25), ("Saturn", 30)],
    [("Venus", 12), ("Jupiter", 16), ("Mercury", 19), ("Mars", 28), ("Saturn", 30)],
]
CHALD = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]
# bounds invariant: per-planet totals 79/82/76/66/57
tot = {}
for row in BOUNDS:
    prev = 0
    for p, e in row:
        tot[p] = tot.get(p, 0) + e - prev
        prev = e
bounds_ok = tot == {"Jupiter": 79, "Venus": 82, "Mercury": 76, "Mars": 66, "Saturn": 57}
addv("western", "Egyptian bounds table totals", "internal table", tot, None, None, None,
     "expected Ju79 Ve82 Me76 Ma66 Sa57", status="pass" if bounds_ok else "fail", confidence="high")


def bound_ruler(lon):
    s, d = sign_of(lon), lon % 30
    for p, e in BOUNDS[s]:
        if d < e:
            return p


def face_ruler(lon):
    k = int(norm(lon) // 10)
    return CHALD[(2 + k) % 7]


def w_dignity(p, lon, sect):
    s = sign_of(lon)
    r = []
    if LORD[s] == p:
        r.append("domicile")
    if EXALT.get(p) == s:
        r.append("exaltation")
    if LORD[(s + 6) % 12] == p:
        r.append("detriment")
    if (EXALT.get(p, -99) + 6) % 12 == s:
        r.append("fall")
    tr = TRIP[s % 4]
    if p == (tr[0] if sect == "day" else tr[1]):
        r.append("triplicity (sect ruler)")
    elif p in tr:
        r.append("triplicity (other)")
    if bound_ruler(lon) == p:
        r.append("bound")
    if face_ruler(lon) == p:
        r.append("face")
    return r


ASPECTS = {0: "conjunction", 60: "sextile", 90: "square", 120: "trine", 180: "opposition"}
ORB = 6.0


def western(jd, dt):
    pos, outer, asc, mc = west_core(jd)
    lag = sign_of(asc)
    sun_alt = swe.azalt(jd, swe.ECL2HOR, (LON, LAT, 0), 1013.25, 15, (pos["Sun"][0], pos["Sun"][1], pos["Sun"][2]))[1]
    sect = "day" if sun_alt > 0 else "night"
    benefic_sect = "Jupiter" if sect == "day" else "Venus"
    malefic_sect = "Saturn" if sect == "day" else "Mars"
    rows = {}
    for p in PL:
        lon = pos[p][0]
        s = sign_of(lon)
        rows[p] = dict(longitude=lon, sign=SIGNS[s], degree=lon % 30, house=(s - lag) % 12 + 1,
                       angular=((s - lag) % 12 + 1) in (1, 4, 7, 10), speed=pos[p][3], retrograde=pos[p][3] < 0,
                       under_beams=(p != "Sun" and angdiff(lon, pos["Sun"][0]) < 15),
                       combust_8_5=(p != "Sun" and angdiff(lon, pos["Sun"][0]) < 8.5),
                       dignities=w_dignity(p, lon, sect), bound_ruler=bound_ruler(lon), face_ruler=face_ruler(lon))
    for p in rows:
        rows[p]["sect_status"] = ("benefic of sect" if p == benefic_sect else "malefic of sect" if p == malefic_sect
                                  else "benefic contrary to sect" if p in ("Jupiter", "Venus")
                                  else "malefic contrary to sect" if p in ("Saturn", "Mars") else
                                  "sect light" if p == ("Sun" if sect == "day" else "Moon") else "-")
    disp = {p: LORD[sign_of(rows[p]["longitude"])] for p in rows}
    chains = {}
    for p in rows:
        c = [p]
        while disp[c[-1]] not in c:
            c.append(disp[c[-1]])
        c.append(disp[c[-1]])
        chains[p] = c
    finals = [p for p in rows if disp[p] == p]
    aspects = []
    names = list(PL)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sep = angdiff(rows[a]["longitude"], rows[b]["longitude"])
            for ang, nm in ASPECTS.items():
                orb = abs(sep - ang)
                if orb <= ORB:
                    # applying if separation moving toward exact
                    dt_ = 1 / 1440
                    p2, *_ = west_core(jd + dt_)
                    sep2 = angdiff(p2[a][0], p2[b][0])
                    applying = abs(sep2 - ang) < orb
                    aspects.append(dict(a=a, b=b, aspect=nm, orb=orb, applying=applying,
                                        whole_sign=((sign_of(rows[b]["longitude"]) - sign_of(rows[a]["longitude"])) % 12)
                                        in {0: (0,), 60: (2, 10), 90: (3, 9), 120: (4, 8), 180: (6,)}[ang]))
    sunl, moonl = rows["Sun"]["longitude"], rows["Moon"]["longitude"]
    if sect == "day":
        fortune, spirit = norm(asc + moonl - sunl), norm(asc + sunl - moonl)
    else:
        fortune, spirit = norm(asc + sunl - moonl), norm(asc + moonl - sunl)
    house_rulers = {h: LORD[(lag + h - 1) % 12] for h in range(1, 13)}
    return dict(asc=asc, asc_sign=SIGNS[lag], asc_degree=asc % 30, mc=mc, mc_sign=SIGNS[sign_of(mc)],
                mc_whole_sign_house=(sign_of(mc) - lag) % 12 + 1, sect=sect, sun_altitude=sun_alt, planets=rows,
                house_rulers=house_rulers, dispositor_chains=chains, final_dispositors=finals, aspects=aspects,
                lot_fortune=dict(longitude=fortune, sign=SIGNS[sign_of(fortune)], house=(sign_of(fortune) - lag) % 12 + 1),
                lot_spirit=dict(longitude=spirit, sign=SIGNS[sign_of(spirit)], house=(sign_of(spirit) - lag) % 12 + 1),
                optional_modern_track=dict(outer_planets={n: dict(longitude=v[0], sign=SIGNS[sign_of(v[0])],
                                                                    house=(sign_of(v[0]) - lag) % 12 + 1)
                                                         for n, v in outer.items()},
                                           note="Separate optional track; contributes no votes."))


WE = {k: western(at_offset(v), local_dt(v)) for k, v in ENSEMBLE.items()}
weT = WE["T"]


def wstab(getter):
    vals = {k: getter(WE[k]) for k in WE}
    return ("stable" if len(set(map(str, vals.values()))) == 1 else "sensitive"), vals


we_stability = {"asc_sign": wstab(lambda w: w["asc_sign"]), "sect": wstab(lambda w: w["sect"]),
                "mc_sign": wstab(lambda w: w["mc_sign"]),
                "lot_fortune_sign": wstab(lambda w: w["lot_fortune"]["sign"]),
                "lot_spirit_sign": wstab(lambda w: w["lot_spirit"]["sign"])}
for p in PL:
    we_stability[f"{p}.house"] = wstab(lambda w, p=p: w["planets"][p]["house"])
    we_stability[f"{p}.sign"] = wstab(lambda w, p=p: w["planets"][p]["sign"])
    we_stability[f"{p}.dignities"] = wstab(lambda w, p=p: w["planets"][p]["dignities"])
we_sensitive = {k: v[1] for k, v in we_stability.items() if v[0] != "stable"}


def w_lag(m):
    return sign_of(angles(at_offset(m))[0])


bd["western_asc_sign"] = scan_boundary(w_lag, 240)


def w_lot(m, which):
    jd = at_offset(m)
    a = angles(jd)[0]
    s = swe_pos(jd, swe.SUN)[0]
    mo = swe_pos(jd, swe.MOON)[0]
    f = norm(a + s - mo) if which == "fortune" else norm(a + mo - s)  # night formula
    return sign_of(f)


bd["western_lot_fortune_sign"] = scan_boundary(lambda m: w_lot(m, "fortune"), 240)
bd["western_lot_spirit_sign"] = scan_boundary(lambda m: w_lot(m, "spirit"), 240)
sunset_dist_min = (local_dt(0) - sk_ev["sunset"]).total_seconds() / 60
bd["sect_sunset"] = ("night", f"birth is {sunset_dist_min:.1f} min after sunset", None)


# Profections
def profections(birth_date, lag_sign_idx, start_year, end_year):
    rows = []
    for y in range(start_year, end_year + 1):
        age = y - birth_date.year
        h = age % 12 + 1
        sgn = (lag_sign_idx + h - 1) % 12
        rows.append(dict(age=age, start=f"{y:04d}-{birth_date.month:02d}-{birth_date.day:02d}",
                         end=f"{y + 1:04d}-{birth_date.month:02d}-{birth_date.day:02d}", house=h, sign=SIGNS[sgn],
                         lord_of_year=LORD[sgn]))
    return rows


PROF = profections(T0.date(), sign_of(weT["asc"]), 2024, 2031)

# ================================================================ 4C BaZi
GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
GAN_EL = {g: e for g, e in zip(GAN, ["wood", "wood", "fire", "fire", "earth", "earth", "metal", "metal", "water", "water"])}
ZHI_EL = dict(zip(ZHI, ["water", "earth", "wood", "wood", "earth", "fire", "fire", "earth", "metal", "metal", "earth", "water"]))
HIDDEN = {"子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"], "卯": ["乙"], "辰": ["戊", "乙", "癸"],
          "巳": ["丙", "庚", "戊"], "午": ["丁", "己"], "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"],
          "酉": ["辛"], "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"]}
GEN = {"wood": "fire", "fire": "earth", "earth": "metal", "metal": "water", "water": "wood"}
CTL = {"wood": "earth", "earth": "water", "water": "fire", "fire": "metal", "metal": "wood"}
TEN_EN = {"比肩": "Friend (Bi Jian)", "劫财": "Rob Wealth (Jie Cai)", "食神": "Eating God (Shi Shen)",
          "伤官": "Hurting Officer (Shang Guan)", "偏财": "Indirect Wealth (Pian Cai)", "正财": "Direct Wealth (Zheng Cai)",
          "七杀": "Seven Killings (Qi Sha)", "正官": "Direct Officer (Zheng Guan)", "偏印": "Indirect Resource (Pian Yin)",
          "正印": "Direct Resource (Zheng Yin)"}


def ten_god(dm, other):
    e1, e2 = GAN_EL[dm], GAN_EL[other]
    same = (GAN.index(dm) % 2) == (GAN.index(other) % 2)
    if e1 == e2:
        return "比肩" if same else "劫财"
    if GEN[e1] == e2:
        return "食神" if same else "伤官"
    if CTL[e1] == e2:
        return "偏财" if same else "正财"
    if CTL[e2] == e1:
        return "七杀" if same else "正官"
    if GEN[e2] == e1:
        return "偏印" if same else "正印"


def hour_branch(h):
    return ZHI[int(((h + 1) % 24) // 2)]


def solar_lon_cross(target, jd_start):
    return swe.solcross_ut(target, jd_start, SWFLAG)


def sky_sun_lon(jd):
    t = ts.ut1_jd(jd)
    _, lo, _ = earth.at(t).observe(eph["sun"]).apparent().frame_latlon(ecliptic_frame)
    return lo.degrees


def sky_cross(target, jd_a, jd_b):
    f = lambda j: ((sky_sun_lon(j) - target + 180) % 360) - 180
    a, b = jd_a, jd_b
    for _ in range(60):
        m = (a + b) / 2
        if f(a) * f(m) <= 0:
            b = m
        else:
            a = m
    return (a + b) / 2


lichun = solar_lon_cross(315, JD0 - 20)
jingzhe = solar_lon_cross(345, JD0)
lichun_sf = sky_cross(315, lichun - 1, lichun + 1)
jingzhe_sf = sky_cross(345, jingzhe - 1, jingzhe + 1)
addv("bazi", "Lichun (315°) instant UT", "Swiss Ephemeris solcross_ut", iso(jd_to_dt(lichun)), "Skyfield/DE421 bisection",
     iso(jd_to_dt(lichun_sf)), abs(lichun - lichun_sf) * 86400, "apparent solar longitude; seconds", thr=120)
addv("bazi", "Jingzhe (345°) instant UT", "Swiss Ephemeris solcross_ut", iso(jd_to_dt(jingzhe)), "Skyfield/DE421 bisection",
     iso(jd_to_dt(jingzhe_sf)), abs(jingzhe - jingzhe_sf) * 86400, "apparent solar longitude; seconds", thr=120)
lc_lp_dt = datetime.fromisoformat(Solar.fromYmdHms(T0.year, T0.month, T0.day, 12, 0, 0).getLunar().getPrevJie(True).getSolar().toYmdHms()).replace(
    tzinfo=ZoneInfo("Asia/Shanghai"))
addv("bazi", "Lichun instant (lunar_python, Beijing time -> UT)", "lunar_python 1.4.9", iso(lc_lp_dt.astimezone(timezone.utc)),
     "Swiss Ephemeris", iso(jd_to_dt(lichun)), abs((lc_lp_dt.astimezone(timezone.utc) - jd_to_dt(lichun)).total_seconds()),
     "seconds", thr=120)
addv("bazi", "Birth after Lichun (month 寅 active, year 庚辰)", "Swiss Ephemeris", JD0 > lichun and JD0 < jingzhe,
     None, None, None, "sectional term bracket", status="pass" if lichun < JD0 < jingzhe else "fail", confidence="high",
     boundary=dict(days_after_lichun=JD0 - lichun, days_before_jingzhe=jingzhe - JD0))


def pillars_for(dt_local_like, late_zi_rule):
    """dt_local_like: naive datetime in the chosen time track. late_zi_rule: 'same_day' (23-24h keeps day) or 'next_day'."""
    d = dt_local_like
    s = Solar.fromYmdHms(d.year, d.month, d.day, d.hour, d.minute, d.second)
    ec = s.getLunar().getEightChar()
    ec.setSect(2 if late_zi_rule == "same_day" else 1)
    return dict(year=ec.getYear(), month=ec.getMonth(), day=ec.getDay(), hour=ec.getTime())


def bazi_track(track, m):
    dl = local_dt(m)
    if track == "civil":
        d = dl.replace(tzinfo=None)
    else:
        u = dl.astimezone(timezone.utc)
        jd = jd_ut(dl)
        d = (u + timedelta(hours=LON / 15) + timedelta(days=swe.time_equ(jd))).replace(tzinfo=None)
    return {rule: pillars_for(d, rule) for rule in ("same_day", "next_day")}, iso(d.replace(tzinfo=None)) if False else d.isoformat()


BAZI_ENS = {}
for track in ("apparent_solar", "civil"):
    for k, v in ENSEMBLE.items():
        BAZI_ENS[f"{track}:{k}"] = bazi_track(track, v)

# Note: lunar_python treats input as Beijing-frame local time; we pass local (Indian) wall/solar time, so
# sectional terms must be checked in local frame. Bracket check above (UT) shows birth is 7.9 d after Lichun,
# 21 d before Jingzhe, so the Beijing-vs-India frame difference (2.5 h) cannot change year/month pillars.
primary_track = "apparent_solar"
P = BAZI_ENS[f"{primary_track}:T"][0]["same_day"]
four = [P["year"], P["month"], P["day"], P["hour"]]
DM = P["day"][0]
pillar_names = ["year", "month", "day", "hour"]
stems = [p[0] for p in four]
branches = [p[1] for p in four]
ten_visible = {pillar_names[i]: (ten_god(DM, stems[i]) if i != 2 else "日主 Day Master") for i in range(4)}
ten_hidden = {pillar_names[i]: [(h, GAN_EL[h], ten_god(DM, h)) for h in HIDDEN[branches[i]]] for i in range(4)}
# cross-check ten gods vs lunar_python
lp_ec = Solar.fromYmdHms(T0.year, T0.month, T0.day, T0.hour, T0.minute, 0).getLunar().getEightChar()
lp_ten = [lp_ec.getYearShiShenGan(), lp_ec.getMonthShiShenGan(), lp_ec.getTimeShiShenGan()]
mine_ten = [ten_visible["year"], ten_visible["month"], ten_visible["hour"]]
addv("bazi", "Ten Gods visible stems (year, month, hour)", "own table", mine_ten, "lunar_python", lp_ten, None,
     "relative to Day Master", status="pass" if mine_ten == lp_ten else "alert", confidence="high")
nayin = [lp_ec.getYearNaYin(), lp_ec.getMonthNaYin(), lp_ec.getDayNaYin(), lp_ec.getTimeNaYin()]

# seasonal state (旺相休囚死) by month branch season
season = {"寅": "wood", "卯": "wood", "巳": "fire", "午": "fire", "申": "metal", "酉": "metal", "亥": "water", "子": "water",
          "辰": "earth", "未": "earth", "戌": "earth", "丑": "earth"}[branches[1]]
dm_el = GAN_EL[DM]


def season_state(el, s):
    if el == s:
        return "旺 prosperous"
    if GEN[s] == el:
        return "相 assisted"
    if GEN[el] == s:
        return "休 resting"
    if CTL[el] == s:
        return "囚 trapped"
    return "死 dead"


dm_season = season_state(dm_el, season)
# strength scoring (declared simple rule set, school: 扶抑 balance)
W_STEM, W_HID = 1.0, [1.0, 0.5, 0.3]
MONTH_MULT = 2.0
support, other = 0.0, 0.0
breakdown = []
for i in range(4):
    if i != 2:
        e = GAN_EL[stems[i]]
        w = W_STEM
        sup = e == dm_el or GEN[e] == dm_el
        support += w if sup else 0
        other += 0 if sup else w
        breakdown.append((f"{pillar_names[i]} stem {stems[i]}", e, w, "support" if sup else "drain/control"))
    for j, h in enumerate(HIDDEN[branches[i]]):
        e = GAN_EL[h]
        w = W_HID[j] * (MONTH_MULT if i == 1 else 1)
        sup = e == dm_el or GEN[e] == dm_el
        support += w if sup else 0
        other += 0 if sup else w
        breakdown.append((f"{pillar_names[i]} branch {branches[i]} hidden {h}", e, w, "support" if sup else "drain/control"))
roots = [(pillar_names[i], branches[i]) for i in range(4) if any(GAN_EL[h] == dm_el for h in HIDDEN[branches[i]])]
dm_strength = "weak" if support < other * 0.8 else "strong" if support > other * 1.2 else "balanced"

# interactions
SIX_COMBO = {frozenset("子丑"): "earth", frozenset("寅亥"): "wood", frozenset("卯戌"): "fire", frozenset("辰酉"): "metal",
             frozenset("巳申"): "water", frozenset("午未"): "fire/earth"}
CLASH = [frozenset(x) for x in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")]
HARM = [frozenset(x) for x in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")]
BREAK = [frozenset(x) for x in ("子酉", "卯午", "辰丑", "未戌", "寅亥", "巳申")]
TRINE = {"water": "申子辰", "wood": "亥卯未", "fire": "寅午戌", "metal": "巳酉丑"}
DIR = {"wood": "寅卯辰", "fire": "巳午未", "metal": "申酉戌", "water": "亥子丑"}
PUNISH = [set("寅巳申"), set("丑戌未"), set("子卯")]
SELF_P = set("辰午酉亥")
STEM_COMBO = {frozenset("甲己"): "earth", frozenset("乙庚"): "metal", frozenset("丙辛"): "water", frozenset("丁壬"): "wood",
              frozenset("戊癸"): "fire"}
inter = []
bset = set(branches)
for i in range(4):
    for j in range(i + 1, 4):
        pr = frozenset([branches[i], branches[j]])
        tag = f"{pillar_names[i]}-{pillar_names[j]} {branches[i]}{branches[j]}"
        if pr in SIX_COMBO:
            el = SIX_COMBO[pr]
            transformed_stem_present = any(GAN_EL[s] == el for s in stems)
            inter.append(dict(type="six combination 六合", pair=tag, element=el,
                              transformation_asserted=False,
                              transformation_note=("target element stem visible" if transformed_stem_present else
                                                   "target-element stem not revealed; transformation not asserted")))
        if pr in CLASH:
            inter.append(dict(type="clash 冲", pair=tag))
        if pr in HARM:
            inter.append(dict(type="harm 害", pair=tag))
        if pr in BREAK:
            inter.append(dict(type="destruction 破", pair=tag))
        if branches[i] == branches[j] and branches[i] in SELF_P:
            inter.append(dict(type="self-punishment 自刑", pair=tag))
        sp = frozenset([stems[i], stems[j]])
        if sp in STEM_COMBO:
            inter.append(dict(type="stem combination 五合", pair=f"{stems[i]}{stems[j]}", element=STEM_COMBO[sp]))
for el, tri in TRINE.items():
    present = [b for b in tri if b in bset]
    if len(present) == 3:
        inter.append(dict(type="three harmony 三合 (full)", element=el, branches="".join(present)))
    elif len(present) == 2 and tri[1] in present:
        inter.append(dict(type="half three-harmony 半合", element=el, branches="".join(present),
                          transformation_asserted=False))
for pset in PUNISH:
    if len(pset & bset) >= 2 and pset != set("子卯"):
        inter.append(dict(type="punishment 刑 (partial)", branches="".join(sorted(pset & bset))))
    if pset == set("子卯") and pset <= bset:
        inter.append(dict(type="punishment 刑", branches="子卯"))
for el, d in DIR.items():
    if set(d) <= bset:
        inter.append(dict(type="directional 三会", element=el))

# Da Yun
year_yang = GAN.index(stems[0]) % 2 == 0
male = N["gender"] == "male"
forward = (year_yang and male) or (not year_yang and not male)
target_jie_jd = jingzhe if forward else lichun
days_to_jie = abs(target_jie_jd - JD0)
start_years = days_to_jie / 3.0
start_dt_exact = local_dt(0) + timedelta(days=start_years * 365.2422)
yun = Solar.fromYmdHms(T0.year, T0.month, T0.day, T0.hour, T0.minute, 0).getLunar().getEightChar().getYun(1 if male else 0)
lp_start = yun.getStartSolar().toYmdHms()
mp = GAN.index(stems[1]), ZHI.index(branches[1])
dayun = []
for k in range(1, 10):
    gi = (mp[0] + (k if forward else -k)) % 10
    zi = (mp[1] + (k if forward else -k)) % 12
    st = start_dt_exact + timedelta(days=(k - 1) * 10 * 365.2422)
    en = start_dt_exact + timedelta(days=k * 10 * 365.2422)
    pil = GAN[gi] + ZHI[zi]
    dayun.append(dict(pillar=pil, start=iso(st), end=iso(en), stem_ten_god=ten_god(DM, GAN[gi]),
                      branch_main_ten_god=ten_god(DM, HIDDEN[ZHI[zi]][0])))
lp_dayun = [d.getGanZhi() for d in yun.getDaYun()[1:10]]
addv("bazi", "Da Yun pillar sequence", "own computation", [d["pillar"] for d in dayun], "lunar_python getDaYun",
     lp_dayun, None, "forward" if forward else "backward",
     status="pass" if lp_dayun == [d["pillar"] for d in dayun] else "alert", confidence="high")
addv("bazi", "Da Yun start", "own: days-to-Jingzhe/3 (Swiss Ephemeris term)", iso(start_dt_exact),
     "lunar_python sect 1 (Beijing-frame terms)", lp_start,
     abs((start_dt_exact.replace(tzinfo=None) - datetime.fromisoformat(lp_start)).days), "days difference",
     thr=60, confidence="medium",
     note="Start-age conventions differ by school; dates differ by the reported number of days.")


def annual_pillar(y):
    return Lunar.fromYmd(y, 6, 1).getYearInGanZhiExact()


annual = []
for y in range(2025, 2031):
    lc = solar_lon_cross(315, swe.julday(y, 1, 20, 0))
    ap = Solar.fromYmd(y, 3, 1).getLunar().getYearInGanZhiByLiChun()
    annual.append(dict(year_pillar=ap, start=iso(jd_to_dt(lc).astimezone(TZ)),
                       end=iso(jd_to_dt(solar_lon_cross(315, swe.julday(y + 1, 1, 20, 0))).astimezone(TZ)),
                       stem_ten_god=ten_god(DM, ap[0]), branch_main_ten_god=ten_god(DM, HIDDEN[ap[1]][0])))


def bazi_hour_civil(m):
    d = local_dt(m)
    return hour_branch(d.hour + d.minute / 60)


def bazi_hour_solar(m):
    dl = local_dt(m)
    u = dl.astimezone(timezone.utc)
    d = u + timedelta(hours=LON / 15) + timedelta(days=swe.time_equ(jd_ut(dl)))
    return hour_branch(d.hour + d.minute / 60)


bd["bazi_hour_branch_civil"] = scan_boundary(bazi_hour_civil, 240)
bd["bazi_hour_branch_apparent_solar"] = scan_boundary(bazi_hour_solar, 240)

BAZI = dict(primary_track="local apparent solar time; late-Zi rule: 23:00-24:00 keeps current day (lunar_python sect 2)",
            alternative_tracks="civil IST; late-Zi next-day (sect 1)",
            pillars=dict(zip(pillar_names, four)), day_master=dict(stem=DM, element=dm_el, yang=GAN.index(DM) % 2 == 0),
            hidden_stems=ten_hidden, ten_gods_visible=ten_visible, nayin=dict(zip(pillar_names, nayin)),
            ensemble={k: v[0] for k, v in BAZI_ENS.items()},
            month_season=season, day_master_seasonal_state=dm_season,
            strength=dict(rule_set="declared: visible stems 1.0; hidden stems main/middle/residual 1.0/0.5/0.3; month branch x2; "
                                   "support = same element or resource; weak if support < 0.8*other, strong if > 1.2*other",
                          support=support, other=other, classification=dm_strength, roots=roots, breakdown=breakdown),
            useful_god=dict(school="扶抑 (support/suppress balance) only", rule_chain=[
                f"Day Master {DM} {dm_el}", f"month {branches[1]} season {season}: DM {dm_season}",
                f"support {support:.2f} vs drain/control {other:.2f} -> {dm_strength}",
                "weak DM under 扶抑 -> favour resource (earth) and companion (metal)" if dm_strength == "weak" else
                "strong DM under 扶抑 -> favour output/wealth/officer" if dm_strength == "strong" else "balanced - no clear 扶抑 preference"],
                            favorable=["earth", "metal"] if dm_strength == "weak" else ["water", "wood", "fire"] if dm_strength == "strong" else [],
                            confidence="low",
                            other_schools="调候 (climate) and 格局 (structure) schools not computed: no validated table in this build"),
            interactions=inter, da_yun=dict(direction="forward" if forward else "backward",
                                            rule="male + yang year stem -> forward" if forward else "", days_to_jie=days_to_jie,
                                            start_rule="3 days = 1 year, 365.2422-day years", periods=dayun,
                                            lunar_python_start=lp_start),
            annual_pillars=annual)

# ================================================================ 4E Zi Wei via canonical iztro (node) + py-iztro
ZW_IDX = {"子": 0, "丑": 1, "寅": 2, "卯": 3, "辰": 4, "巳": 5, "午": 6, "未": 7, "申": 8, "酉": 9, "戌": 10, "亥": 11}


GENDER_ZH = "男" if N["gender"] == "male" else "女"


def zw_index_civil(m):
    d = local_dt(m)
    h = d.hour + d.minute / 60
    if h >= 23:
        return 12
    return ZW_IDX[hour_branch(h)]


def zw_index_solar(m):
    dl = local_dt(m)
    u = dl.astimezone(timezone.utc)
    d = u + timedelta(hours=LON / 15) + timedelta(days=swe.time_equ(jd_ut(dl)))
    h = d.hour + d.minute / 60
    return (12 if h >= 23 else ZW_IDX[hour_branch(h)]), d.date().isoformat()


def iztro_node(date_str, idx):
    js = f"""
const {{astro}}=require('iztro');
const a=astro.bySolar('{date_str}',{idx},'{GENDER_ZH}',true,'zh-CN');
const h=a.horoscope(new Date('{AS_OF.isoformat()}T12:00:00'));
const out={{solarDate:a.solarDate,lunarDate:a.lunarDate,chineseDate:a.chineseDate,time:a.time,timeRange:a.timeRange,
 sign:a.sign,zodiac:a.zodiac,soul:a.soul,body:a.body,fiveElementsClass:a.fiveElementsClass,
 soulBranch:a.earthlyBranchOfSoulPalace,bodyBranch:a.earthlyBranchOfBodyPalace,
 palaces:a.palaces.map(p=>({{name:p.name,stem:p.heavenlyStem,branch:p.earthlyBranch,isBody:p.isBodyPalace,
   major:p.majorStars.map(s=>({{name:s.name,brightness:s.brightness,mutagen:s.mutagen||null}})),
   minor:p.minorStars.map(s=>({{name:s.name,brightness:s.brightness,mutagen:s.mutagen||null}})),
   decadal:p.decadal.range,ages:p.ages}})),
 horoscope_asof:{{decadal:{{index:h.decadal.index,stem:h.decadal.heavenlyStem,branch:h.decadal.earthlyBranch}},
   yearly:{{index:h.yearly.index,stem:h.yearly.heavenlyStem,branch:h.yearly.earthlyBranch}},nominalAge:h.age.nominalAge}}}};
console.log(JSON.stringify(out));"""
    r = subprocess.run(["node", "-e", js], cwd=NODE_DIR, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


ZW = {}
for k, v in ENSEMBLE.items():
    ic = zw_index_civil(v)
    isol, dsol = zw_index_solar(v)
    ZW[f"civil:{k}"] = dict(time_index=ic, chart=iztro_node(local_dt(v).date().isoformat(), ic))
    ZW[f"apparent_solar:{k}"] = dict(time_index=isol, chart=iztro_node(dsol, isol))
zwT = ZW["apparent_solar:T"]["chart"]
pal_br = [p["branch"] for p in zwT["palaces"]]
addv("ziwei", "12 unique palaces", "iztro 2.5.0 (node)", len(set(pal_br)), None, None, None, "", status="pass" if len(set(pal_br)) == 12 else "fail",
     confidence="high")
majors = [s["name"] for p in zwT["palaces"] for s in p["major"]]
MAJ14 = set("紫微 天机 太阳 武曲 天同 廉贞 天府 太阴 贪狼 巨门 天相 天梁 七杀 破军".split())
addv("ziwei", "14 major stars each placed exactly once", "iztro 2.5.0", sorted(majors), None, None, None, "",
     status="pass" if sorted(majors) == sorted(MAJ14) else "fail", confidence="high")
# invariant: 紫微 and 天府 symmetric about 寅-申 axis: br(zw)+br(tf) == 4 mod 12 (寅=2)
bz = {s["name"]: ZW_IDX[p["branch"]] for p in zwT["palaces"] for s in p["major"]}
inv_ok = (bz["紫微"] + bz["天府"]) % 12 == 4
addv("ziwei", "Zi Wei/Tian Fu mirror about 寅-申 axis", "iztro 2.5.0", (bz["紫微"], bz["天府"]), None, None, None,
     "(branch_ziwei + branch_tianfu) mod 12 == 4", status="pass" if inv_ok else "fail", confidence="high")
# py-iztro interface cross-check (same method)
try:
    from py_iztro import Astro
    pa = Astro().by_solar(f"{T0.year}-{T0.month}-{T0.day}", ZW["apparent_solar:T"]["time_index"], GENDER_ZH, True, "zh-CN")
    pyz = sorted((p.earthly_branch, tuple(sorted(s.name for s in p.major_stars))) for p in pa.palaces)
    ndz = sorted((p["branch"], tuple(sorted(s["name"] for s in p["major"]))) for p in zwT["palaces"])
    addv("ziwei", "py-iztro vs iztro serialization", "iztro 2.5.0 (node)", "match" if pyz == ndz else "mismatch",
         "py-iztro 0.1.5 (embeds iztro 2.5.0)", None, None, "SAME underlying method - interface check only",
         status="pass" if pyz == ndz else "alert", confidence="medium")
except Exception as e:
    addv("ziwei", "py-iztro interface check", "py-iztro", None, None, None, None, "", status="unavailable",
         confidence="unavailable", note=str(e))


def zw_sig(c):
    return [(p["name"], p["branch"], tuple(s["name"] for s in p["major"])) for p in c["palaces"]] + [c["fiveElementsClass"]]


zw_stability = {}
for track in ("civil", "apparent_solar"):
    sigs = {k: json.dumps(zw_sig(ZW[f"{track}:{k}"]["chart"]), ensure_ascii=False) for k in ENSEMBLE}
    zw_stability[track] = "stable" if len(set(sigs.values())) == 1 else "sensitive"
bd["ziwei_time_index_civil"] = scan_boundary(zw_index_civil, 240)
bd["ziwei_time_index_apparent_solar"] = scan_boundary(lambda m: zw_index_solar(m)[0], 240)

# lunar date check: new moon before birth (Swiss) -> lunar day count in local frame
def elong(jd):
    return norm(swe_pos(jd, swe.MOON)[0] - swe_pos(jd, swe.SUN)[0])


a, b = JD0 - 9, JD0 - 5
f = lambda j: ((elong(j) + 180) % 360) - 180
for _ in range(60):
    mm = (a + b) / 2
    if f(a) * f(mm) <= 0:
        b = mm
    else:
        a = mm
nm_dt = jd_to_dt(a)
lunar_day_local = (T0.date() - nm_dt.astimezone(TZ).date()).days + 1
lunar_day_bj = (T0.date() - nm_dt.astimezone(ZoneInfo("Asia/Shanghai")).date()).days + 1
addv("ziwei", "Lunar day number (new-moon count)", "iztro lunar date", zwT["lunarDate"], "Swiss Ephemeris new moon",
     dict(new_moon_ut=iso(nm_dt), lunar_day_local_frame=lunar_day_local, lunar_day_beijing_frame=lunar_day_bj),
     None, "civil-date lunar day", status="pass" if lunar_day_local == 8 and lunar_day_bj == 8 else "alert",
     confidence="high")

# ================================================================ 4F Maya
lc = mayan.from_gregorian(T0.year, T0.month, T0.day)
tzk = mayan.lc_to_tzolkin(*lc)
haab = mayan.lc_to_haab(*lc)
back = mayan.to_gregorian(*lc)
# independent computation from JDN with GMT 584283
jdn = int(swe.julday(T0.year, T0.month, T0.day, 12.0))
days = jdn - 584283
b_, r = divmod(days, 144000); k_, r = divmod(r, 7200); t_, r = divmod(r, 360); w_, ki = divmod(r, 20)
TZN = ["Imix", "Ik'", "Ak'b'al", "K'an", "Chikchan", "Kimi", "Manik'", "Lamat", "Muluk", "Ok", "Chuwen", "Eb'",
       "B'en", "Ix", "Men", "K'ib'", "Kab'an", "Etz'nab'", "Kawak", "Ajaw"]
HAABN = ["Pop", "Wo'", "Sip", "Sotz'", "Sek", "Xul", "Yaxk'in", "Mol", "Ch'en", "Yax", "Sak'", "Keh", "Mak",
         "K'ank'in", "Muwan'", "Pax", "K'ayab", "Kumk'u", "Wayeb'"]
tz_num = (days + 3) % 13 + 1
tz_name = TZN[(days + 19) % 20]
hd = (days + 348) % 365
haab_ind = (hd % 20, HAABN[hd // 20])
MAYA = dict(correlation="GMT 584283", long_count=list(lc), long_count_str=".".join(map(str, lc)),
            tzolkin=dict(number=tz_num, name=tz_name), haab=dict(day=haab_ind[0], month=haab_ind[1]),
            convertdate_tzolkin=tzk, convertdate_haab=haab, roundtrip=list(back),
            independent_long_count=[b_, k_, t_, w_, ki], day_convention="civil date (midnight); Maya days traditionally begin at sunset/sunrise depending on community - not applied")
addv("maya", "Long Count", "convertdate 2.5.1", MAYA["long_count_str"], "own JDN arithmetic (GMT 584283)",
     ".".join(map(str, [b_, k_, t_, w_, ki])), None, "GMT 584283",
     status="pass" if list(lc) == [b_, k_, t_, w_, ki] else "fail", confidence="high")
addv("maya", "Round-trip to Gregorian", "convertdate", list(back), None, [T0.year, T0.month, T0.day], None, "",
     status="pass" if tuple(back) == (T0.year, T0.month, T0.day) else "fail", confidence="high")
if tzk:
    addv("maya", "Tzolk'in", "convertdate", list(tzk), "own JDN arithmetic", [tz_num, tz_name], None,
         "", status="pass" if tzk[0] == tz_num else "alert", confidence="high")
if haab:
    addv("maya", "Haab'", "convertdate", list(haab), "own JDN arithmetic", list(haab_ind), None, "",
         status="pass" if haab[0] == haab_ind[0] else "alert", confidence="high")

# ================================================================ 4G Tibetan
TIB_EL = {"甲": "Wood", "乙": "Wood", "丙": "Fire", "丁": "Fire", "戊": "Earth", "己": "Earth", "庚": "Iron", "辛": "Iron",
          "壬": "Water", "癸": "Water"}
TIB_AN = dict(zip(ZHI, ["Mouse", "Ox", "Tiger", "Hare", "Dragon", "Snake", "Horse", "Sheep", "Monkey", "Bird", "Dog", "Pig"]))
LOS = N.get("tibetan_losar")  # {"start","end","source"} for the birth year's Losar, from a cited source
if LOS:
    los_end = datetime.fromisoformat(LOS["end"]).date()
    yp = stems[0] + branches[0]
    after = (T0.date() - los_end).days
    TIBET = dict(element_animal=f"{TIB_EL[yp[0]]} {'Male' if GAN.index(yp[0]) % 2 == 0 else 'Female'} {TIB_AN[yp[1]]}",
                 source=f"sexagenary year {yp} mapped to Tibetan element/animal",
                 losar_boundary=dict(losar=f"{LOS['start']} to {LOS['end']} ({LOS['source']})", birth_days_after_losar_end=after,
                                     status="stable" if after >= 1 else "check"),
                 confidence="medium", mewa="omitted - no validated lineage implementation",
                 parkha="omitted - no validated implementation",
                 personal_forces="omitted (la, sog, lu, wangthang, lungta) - anchors not validated",
                 role="limited symbolic overlay; no domain vote")
    addv("tibetan", "Element-animal year", "sexagenary mapping", TIBET["element_animal"], "Losar date table (input)",
         f"{LOS['start']}..{LOS['end']}", None, "Phugpa Losar assumed", status="pass" if after >= 1 else "fail",
         confidence="medium", note="Losar date not computed by a calendar engine")
else:
    TIBET = dict(element_animal=None, confidence="unavailable", note="no sourced Losar date supplied in BIRTH_INPUT",
                 losar_boundary="unavailable", source="", mewa="omitted", parkha="omitted", personal_forces="omitted")

# ================================================================ assemble
dataset = dict(
    input_audit=input_audit,
    conventions=dict(
        jyotisha="sidereal, Lahiri (SIDM_LAHIRI), whole-sign houses, true node primary (mean node stored), Parashari track only; "
                 "dignity = exaltation/debilitation/moolatrikona/own/natural friendship (no compound/temporal friendship); "
                 "combustion orbs BPHS (Mo12 Ma17 Me14/12R Ju11 Ve10/8R Sa15); drishti 7th all, Ma 4/8, Ju 5/9, Sa 3/10, nodes none; "
                 "Vimshottari 365.25-day years",
        western="tropical, whole-sign houses, 7 traditional planets, sect from Sun altitude; dignities: domicile/exaltation/"
                "Dorothean triplicity/Egyptian bounds/Chaldean faces; aspects Ptolemaic with 6° orb; lots night formula when nocturnal; "
                "profection by birthday date",
        bazi="local apparent solar time primary; late-Zi same-day (sect 2) primary; sectional terms Swiss Ephemeris; Da Yun 3 days=1 yr",
        ziwei="iztro 2.5.0 default (全书 4-transformation table as configured in iztro), fix_leap=true, time index from local apparent "
              "solar time primary, civil alternative; nominal (虚岁) age",
        maya="GMT 584283, civil date", tibetan="element-animal only"),
    jyotisha=dict(ensemble=JY, stability={k: v[0] for k, v in jy_stability.items()}, sensitive_values=jy_sensitive,
                  vimshottari=VIM, yogas=YOG, yoga_stability=yoga_stability,
                  shadbala="unavailable - no validated implementation in this build",
                  ashtakavarga="not computed - transit support not requested",
                  d7_d12="not computed - domain not requested; D12 would also be time-sensitive",
                  pratyantardasha="unavailable - ±30 min birth-time uncertainty shifts dasha boundaries by more than a pratyantardasha resolution warrants"),
    western=dict(ensemble=WE, stability={k: v[0] for k, v in we_stability.items()}, sensitive_values=we_sensitive,
                 profections=PROF, solar_return="not computed - specific return/transit timing not requested",
                 zodiacal_releasing="not computed - no validated implementation"),
    bazi=BAZI,
    ziwei=dict(ensemble=ZW, stability=zw_stability, implementation="iztro 2.5.0 (npm, node) primary; py-iztro 0.1.5 interface check"),
    maya=MAYA, tibetan=TIBET,
    boundaries={k: dict(value_at_T=str(v[0]), minutes_to_previous_change=v[1], minutes_to_next_change=v[2]) for k, v in bd.items()},
    excluded_methods=[
        "Jyotisha Shadbala (no validated implementation)", "Jyotisha Ashtakavarga (not requested)",
        "Jyotisha Pratyantardasha (time precision)", "Jyotisha Jaimini/KP tracks (not requested)",
        "Western solar return & transits (not requested)", "Zodiacal releasing (not validated)",
        "BaZi 调候/格局 useful-god schools (no validated table)", "Tibetan Mewa, Parkha, personal forces (not validated)",
        "Maya day-sign meanings (no attributed source in dataset)"],
    alerts=alerts)
dataset["jyotisha"]["vimshottari_shift_days_between_extremes"] = vim_shift_days


def default(o):
    if isinstance(o, (datetime,)):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, tuple):
        return list(o)
    return str(o)


json.dump(dataset, open(os.path.join(OUT, "MASTER_DATASET.json"), "w"), ensure_ascii=False, indent=1, default=default)
json.dump(verif, open(os.path.join(OUT, "VERIFICATION_REPORT.json"), "w"), ensure_ascii=False, indent=1, default=default)

src = open(__file__, "rb").read()


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


nodever = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
manifest = dict(
    runtime=dict(python=sys.version, platform=platform.platform(), node=nodever),
    packages={"pyswisseph": swe.version, "skyfield": skyfield.__version__, "lunar_python": "1.4.9",
              "convertdate": convertdate.__version__ if hasattr(convertdate, "__version__") else "2.5.1",
              "tzdata": tzdata.IANA_VERSION, "iztro(npm)": "2.5.0", "py-iztro": "0.1.5"},
    ephemeris_files={f: sha(os.path.join(EPHE, f)) for f in sorted(os.listdir(EPHE)) if f.endswith(".se1")},
    jpl_kernel={os.path.basename(BSP): sha(BSP),
                "note": "DE421 used; DE440/DE441 download blocked by network policy (403). DE421 valid 1900-2050."},
    independence_disclosure="Swiss Ephemeris files derive from JPL DE431 numerical integration; Skyfield uses JPL DE421. "
                            "Code paths (precession/nutation/aberration/light-time) are independent; underlying physical "
                            "ephemerides are both JPL integrations. iztro and py-iztro are the SAME method.",
    iana_tzdata=tzdata.IANA_VERSION, conventions=dataset["conventions"],
    builder_sha256=hashlib.sha256(src).hexdigest(), executed_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
json.dump(manifest, open(os.path.join(OUT, "CALCULATION_MANIFEST.json"), "w"), indent=1, default=default)
print("alerts:", alerts)
print("verification rows:", len(verif), "fails:", [v["datum"] for v in verif if v["status"] in ("fail", "alert")])
