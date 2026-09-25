"""Сводка этапа 3: один лучший опубликованный имейл на врача + схемы адресов по доменам.

Вход: out/stage2_oncologists.csv, out/pubmed_emails.csv, out/trials_emails.csv
Выход: out/published_emails.csv (npi → email) и out/domain_patterns.csv (домен → схема, сколько подтверждений)
"""
import csv, json, re, unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "me.com", "msn.com",
             "live.com", "comcast.net", "protonmail.com", "163.com", "qq.com"}


def fold(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())


def pattern_of(local, d):
    """Какой шаблон даёт этот локальный адрес для данного врача (или None)."""
    f, m, l = fold(d["first_name"]), fold(d["middle_name"]), fold(d["last_name"])
    if not f or not l:
        return None
    local = local.lower()
    cands = {
        "first.last": f"{f}.{l}", "firstlast": f"{f}{l}", "first_last": f"{f}_{l}", "flast": f"{f[0]}{l}",
        "f.last": f"{f[0]}.{l}", "firstl": f"{f}{l[0]}", "first.l": f"{f}.{l[0]}", "last.first": f"{l}.{f}",
        "lastf": f"{l}{f[0]}", "last": l, "first": f, "last_first": f"{l}_{f}", "lastfirst": f"{l}{f}",
        "first-last": f"{f}-{l}",
    }
    if m:
        cands.update({"first.m.last": f"{f}.{m[0]}.{l}", "fmlast": f"{f[0]}{m[0]}{l}", "firstmlast": f"{f}{m[0]}{l}",
                      "first.mlast": f"{f}.{m[0]}{l}", "fml": f"{f[0]}{m[0]}{l[0]}"})
    # «flast7» и т.п. — шаблон с обрезкой фамилии до n букв
    for name, value in cands.items():
        if local == value:
            return name
    for n in range(4, 9):
        if len(l) > n and local == f"{f[0]}{l[:n]}":
            return f"flast{n}"
    return None


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def other_people_emails():
    """Все пары (человек, имейл) из скачанных статей и исследований — для обучения схем доменов."""
    for x in sorted((ROOT / "data" / "pubmed_cache").glob("*.xml")):
        try:
            root = ET.parse(x).getroot()
        except ET.ParseError:
            continue
        for au in root.iter("Author"):
            fore = (au.findtext("ForeName") or "").split()
            person = {"first_name": fore[0] if fore else "", "middle_name": fore[1] if len(fore) > 1 else "",
                      "last_name": au.findtext("LastName") or ""}
            for aff in au.iter("Affiliation"):
                for e in EMAIL.findall(aff.text or ""):
                    yield person, e.rstrip(".").lower()
    ct = ROOT / "data" / "ctgov_cache.jsonl"
    for line in open(ct) if ct.exists() else []:
        clm = json.loads(line).get("protocolSection", {}).get("contactsLocationsModule", {})
        contacts = clm.get("centralContacts", []) + [c for l in clm.get("locations", []) for c in l.get("contacts", [])]
        for c in contacts:
            parts = re.sub(r",.*$", "", c.get("name", "")).split()
            if c.get("email") and len(parts) >= 2:
                yield {"first_name": parts[0], "middle_name": parts[1] if len(parts) > 2 else "", "last_name": parts[-1]}, c["email"].strip().lower()


def main():
    docs = {d["npi"]: d for d in csv.DictReader(open(OUT / "stage2_oncologists.csv", encoding="utf-8"))}
    found = defaultdict(list)  # npi -> [(priority, year, email, source)]
    for r in csv.DictReader(open(OUT / "pubmed_emails.csv", encoding="utf-8")):
        found[r["npi"]].append((0 if r["name_in_email"] == "yes" else 2, int(r["year"] or 0), r["email"], f"pubmed:{r['pmid']}"))
    for r in csv.DictReader(open(OUT / "trials_emails.csv", encoding="utf-8")):
        found[r["npi"]].append((0 if r["name_in_email"] == "yes" else 3, 2026, r["email"], f"clinicaltrials:{r['nct']}"))

    best, patterns = {}, defaultdict(Counter)
    for npi, items in found.items():
        # личный адрес с фамилией > самый свежий; общие ящики исследовательских офисов — в последнюю очередь
        items.sort(key=lambda x: (x[0], -x[1]))
        prio, year, email, src = items[0]
        best[npi] = {"npi": npi, "email": email, "email_source": src, "email_year": year or "",
                     "email_type": "personal" if prio == 0 else ("unverified_owner" if prio == 2 else "research_office"),
                     "other_emails": "; ".join(sorted({e for _, _, e, _ in items} - {email}))}

    # схемы учим на всех людях из статей и исследований (наши онкологи туда тоже входят)
    seen = set()
    for person, e in other_people_emails():
        if (e, person["last_name"]) in seen or "@" not in e:
            continue
        seen.add((e, person["last_name"]))
        local, domain = e.split("@", 1)
        if domain not in FREE_MAIL and (p := pattern_of(local, person)):
            patterns[domain][p] += 1

    with open(OUT / "published_emails.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["npi", "email", "email_type", "email_source", "email_year", "other_emails"])
        w.writeheader()
        w.writerows(best.values())
    with open(OUT / "domain_patterns.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "top_pattern", "top_count", "total_examples", "share", "all_patterns"])
        for dom, c in sorted(patterns.items(), key=lambda x: -sum(x[1].values())):
            (p, n), total = c.most_common(1)[0], sum(c.values())
            w.writerow([dom, p, n, total, round(n / total, 2), "; ".join(f"{k}:{v}" for k, v in c.most_common())])
    types = Counter(b["email_type"] for b in best.values())
    print(f"врачей с опубликованным имейлом: {len(best):,}  {dict(types)}")
    print(f"доменов со схемой: {len(patterns):,}; с ≥2 подтверждениями: {sum(1 for c in patterns.values() if sum(c.values()) >= 2):,}")


if __name__ == "__main__":
    main()
