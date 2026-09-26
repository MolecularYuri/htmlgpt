"""Этап 6 (опционально): вероятный рабочий адрес по схеме домена учреждения.

Только для врачей без опубликованного адреса. Результат идёт в отдельную колонку pattern_email:
по DPDP Act такие адреса не считаются «сделанными публичными самим человеком», решение — за клиентом.

1. Схемы доменов учим на всех парах «автор → имейл» из скачанных статей (метаданные + полные тексты).
2. Домен учреждения — по коллегам из того же учреждения с опубликованным институциональным адресом.
3. Точность проверяем на врачах с известным институциональным адресом (hold-out).
Вход/выход: out/india_oncologists.csv (добавляются колонки pattern_email, pattern_confidence).
"""
import csv, glob, json, re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from stage3_build import fold, EMAIL

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "out"
FREE = {"gmail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "hotmail.com", "rediffmail.com", "outlook.com", "ymail.com",
        "live.com", "icloud.com", "rocketmail.com", "googlemail.com", "hotmail.co.in", "outlook.in", "aol.com", "protonmail.com"}


def patterns_for(first, middle, last):
    f, m, l = fold(first), fold(middle), fold(last)
    if not f or not l:
        return {}
    c = {"first.last": f"{f}.{l}", "firstlast": f"{f}{l}", "first_last": f"{f}_{l}", "flast": f"{f[0]}{l}",
         "f.last": f"{f[0]}.{l}", "firstl": f"{f}{l[0]}", "first.l": f"{f}.{l[0]}", "last.first": f"{l}.{f}",
         "lastf": f"{l}{f[0]}", "first": f, "last": l, "lastfirst": f"{l}{f}", "dr.first.last": f"dr.{f}.{l}", "drfirst": f"dr{f}",
         "drfirstlast": f"dr{f}{l}"}
    if m:
        c.update({"first.m.last": f"{f}.{m[0]}.{l}", "fmlast": f"{f[0]}{m[0]}{l}", "firstmlast": f"{f}{m[0]}{l}"})
    return c


def split_first(first):
    parts = (first or "").replace(".", " ").split()
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


def pairs():
    """(first, middle, last, email) для всех авторов с имейлом в скачанных статьях."""
    for line in open(DATA / "epmc_core.jsonl"):
        for a in json.loads(line).get("authorList", {}).get("author", []):
            for x in a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", []):
                for e in EMAIL.findall(x.get("affiliation", "")):
                    f, m = split_first(a.get("firstName"))
                    yield f, m, a.get("lastName", ""), e.lower().rstrip(".")
    for p in glob.glob(str(DATA / "fulltext" / "*.xml")):
        try:
            root = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        for c in root.iter("contrib"):
            n = c.find(".//name")
            if n is None:
                continue
            f, m = split_first(n.findtext("given-names"))
            for el in c.iter("email"):
                for e in EMAIL.findall("".join(el.itertext())):
                    yield f, m, n.findtext("surname") or "", e.lower().rstrip(".")


def main():
    pats, seen = defaultdict(Counter), set()
    for f, m, l, e in pairs():
        local, dom = e.split("@", 1)
        if dom in FREE or (e, fold(l)) in seen:
            continue
        seen.add((e, fold(l)))
        for name, val in patterns_for(f, m, l).items():
            if local == val:
                pats[dom][name] += 1
                break

    rows = list(csv.DictReader(open(OUT / "india_oncologists.csv", encoding="utf-8")))
    org_dom = defaultdict(Counter)
    for r in rows:
        for e in [r["email"]] + r["other_emails"].split("; "):
            if e and "@" in e and e.split("@")[1] not in FREE and r["institution"]:
                org_dom[fold(r["institution"])[:30]][e.split("@")[1]] += 1

    def guess(r):
        c = org_dom.get(fold(r["institution"])[:30])
        if not c:
            return None
        dom, n = c.most_common(1)[0]
        if "tatamemorial" in fold(r["institution"]) and dom == "actrec.gov.in":
            dom, n = "tmc.gov.in", max(n, c.get("tmc.gov.in", 0), 2)  # врачи Tata Memorial — tmc.gov.in, ACTREC — исследовательский центр
        pc = pats.get(dom)
        if n < 2 or not pc or sum(pc.values()) < 3:
            return None
        pat, k = pc.most_common(1)[0]
        share = k / sum(pc.values())
        f, m = split_first(r["first_name"])
        local = patterns_for(f, m, r["last_name"]).get(pat)
        return (f"{local}@{dom}", share, pat) if local and share >= 0.5 else None

    # проверка точности на тех, у кого известен институциональный адрес
    ok = tot = 0
    for r in rows:
        if r["email_type"] == "published_personal" and r["email"].split("@")[1] not in FREE:
            g = guess(r)
            if g:
                tot += 1
                ok += g[0] == r["email"]
    acc = ok / tot if tot else 0
    print(f"схем доменов: {len(pats)}; проверка на {tot} врачах с известным адресом: точность {acc:.0%}")

    added = 0
    for r in rows:
        r["pattern_email"] = r["pattern_confidence"] = ""
        if r["email_type"] in ("published_personal", "trial_contact"):
            continue
        g = guess(r)
        if g:
            r["pattern_email"] = g[0]
            r["pattern_confidence"] = "high" if g[1] >= 0.9 else "medium" if g[1] >= 0.7 else "low"
            added += 1
    with open(OUT / "india_oncologists.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"вероятный адрес по схеме домена: {added:,} врачей "
          f"{dict(Counter(r['pattern_confidence'] for r in rows if r['pattern_confidence']))}")


if __name__ == "__main__":
    main()
