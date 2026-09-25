"""Этап 3б: имейлы исследователей из ClinicalTrials.gov (API v2).

Берём онкологические исследования с центрами в США, обновлённые с 2019 года, и вытаскиваем
контакты (центральные и по центрам), у которых указан имейл. Контакт присваиваем врачу,
если совпадают имя+фамилия и штат центра совпадает со штатом врача.

Вход: out/stage1_oncologists.csv. Выход: out/trials_emails.csv (+ кэш data/ctgov_cache.jsonl).
"""
import csv, json, re, sys, time, unicodedata, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT, CACHE = ROOT / "out", ROOT / "data" / "ctgov_cache.jsonl"
API = "https://clinicaltrials.gov/api/v2/studies"
STATE_ABBR = {v.lower(): k for k, v in {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico"}.items()}
CRED = re.compile(r",?\s*\b(MD|M\.D\.|DO|PhD|Ph\.D\.|MPH|MS|MSc|MBBS|FACP|RN|BSN|MBA|FRCPC|MHS|MSCI|MSCR)\b\.?", re.I)


def fold(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())


def split_name(name):
    name = CRED.sub("", name).strip(" ,")
    if "," in name:  # "Smith, John"
        last, first = [p.strip() for p in name.split(",", 1)]
    else:
        parts = name.split()
        if len(parts) < 2:
            return None
        first, last = parts[0], parts[-1]
    return fold(last), fold(first.split()[0]) if first else ""


def download():
    if CACHE.exists():
        return
    params = {"query.cond": "cancer OR neoplasm OR tumor OR lymphoma OR leukemia OR myeloma",
              "query.locn": "United States", "filter.advanced": "AREA[LastUpdatePostDate]RANGE[2019-01-01,MAX]",
              "fields": "NCTId,BriefTitle,OverallStatus,LeadSponsorName,CentralContactName,CentralContactEMail,CentralContact,"
                        "OverallOfficial,Location", "pageSize": 1000, "format": "json"}
    tmp, token, n = CACHE.with_suffix(".part"), None, 0
    with open(tmp, "w") as f:
        while True:
            q = dict(params, **({"pageToken": token} if token else {}))
            for attempt in range(5):
                try:
                    page = json.load(urllib.request.urlopen(API + "?" + urllib.parse.urlencode(q), timeout=120))
                    break
                except Exception as e:
                    print(f"  повтор: {e}"); time.sleep(2 ** attempt)
            for s in page.get("studies", []):
                f.write(json.dumps(s) + "\n")
            n += len(page.get("studies", []))
            print(f"  исследований: {n:,}")
            token = page.get("nextPageToken")
            if not token:
                break
    tmp.rename(CACHE)


def contacts(study):
    ps = study.get("protocolSection", {})
    nct = ps.get("identificationModule", {}).get("nctId", "")
    clm = ps.get("contactsLocationsModule", {})
    states = {STATE_ABBR.get((l.get("state") or "").lower()) for l in clm.get("locations", [])}
    for c in clm.get("centralContacts", []):
        if c.get("email"):
            yield nct, c.get("name", ""), c["email"], states, "central"
    for loc in clm.get("locations", []):
        st = {STATE_ABBR.get((loc.get("state") or "").lower())}
        for c in loc.get("contacts", []):
            if c.get("email"):
                yield nct, c.get("name", ""), c["email"], st, "site:" + (loc.get("facility") or "")[:80]


def main():
    download()
    docs = list(csv.DictReader(open(OUT / "stage1_oncologists.csv", encoding="utf-8")))
    by_name = {}
    for d in docs:
        by_name.setdefault((fold(d["last_name"]), fold(d["first_name"])), []).append(d)
    rows, seen = [], set()
    for line in open(CACHE):
        for nct, name, email, states, where in contacts(json.loads(line)):
            key = split_name(name)
            for d in by_name.get(key, []) if key else []:
                email = email.strip().lower()
                if d["state"] in states and (d["npi"], email) not in seen:
                    seen.add((d["npi"], email))
                    rows.append({"npi": d["npi"], "email": email, "nct": nct, "where": where,
                                 "name_in_email": "yes" if fold(d["last_name"])[:5] in fold(email.split("@")[0]) else "no"})
    with open(OUT / "trials_emails.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["npi", "email", "nct", "where", "name_in_email"])
        w.writeheader()
        w.writerows(rows)
    print(f"готово: имейлы из ClinicalTrials.gov у {len({r['npi'] for r in rows}):,} врачей")


if __name__ == "__main__":
    main()
