"""Этап 5: достраиваем имейлы по схеме адресов организации.

1. Домен организации: по коллегам из той же клиники (CMS group) или больницы, у которых уже есть
   опубликованный личный имейл. Берём домен, если за него ≥2 коллеги и он преобладает (≥60%).
2. Схема адреса домена: из out/domain_patterns.csv (≥3 примера и доля ≥50%).
3. Строим адрес. Такие адреса помечаются pattern_high / pattern_medium / pattern_low — перед рассылкой их нужно
   прогнать через сервис проверки (MillionVerifier / ZeroBounce / NeverBounce).

Вход: out/stage2_oncologists.csv, out/published_emails.csv, out/domain_patterns.csv
Выход: out/final_oncologists.csv
"""
import csv, re
from collections import Counter, defaultdict
from pathlib import Path
from stage4_merge import fold

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
MIN_COLLEAGUES, MIN_DOMAIN_SHARE, MIN_PATTERN_EXAMPLES, MIN_PATTERN_SHARE = 2, 0.6, 3, 0.5


def orgs(d):
    return [("clinic", x.strip()) for x in d.get("clinic", "").split(";") if x.strip()] + \
           [("hospital", x.strip()) for x in d.get("hospitals", "").split(";") if x.strip() and not x.strip().startswith("CCN")]


def build(pattern, d):
    f, m, l = fold(d["first_name"]), fold(d["middle_name"]), fold(d["last_name"])
    if not f or not l:
        return None
    if pattern.startswith("flast") and pattern[5:].isdigit():
        return f"{f[0]}{l[:int(pattern[5:])]}"
    table = {"first.last": f"{f}.{l}", "firstlast": f"{f}{l}", "first_last": f"{f}_{l}", "flast": f"{f[0]}{l}",
             "f.last": f"{f[0]}.{l}", "firstl": f"{f}{l[0]}", "first.l": f"{f}.{l[0]}", "last.first": f"{l}.{f}",
             "lastf": f"{l}{f[0]}", "last": l, "first": f, "last_first": f"{l}_{f}", "lastfirst": f"{l}{f}",
             "first-last": f"{f}-{l}"}
    if m:
        table.update({"first.m.last": f"{f}.{m[0]}.{l}", "fmlast": f"{f[0]}{m[0]}{l}", "firstmlast": f"{f}{m[0]}{l}",
                      "first.mlast": f"{f}.{m[0]}{l}", "fml": f"{f[0]}{m[0]}{l[0]}"})
    return table.get(pattern)


def main():
    docs = list(csv.DictReader(open(OUT / "stage2_oncologists.csv", encoding="utf-8")))
    pub = {r["npi"]: r for r in csv.DictReader(open(OUT / "published_emails.csv", encoding="utf-8"))}
    pats = {r["domain"]: r for r in csv.DictReader(open(OUT / "domain_patterns.csv", encoding="utf-8"))}

    org_domains = defaultdict(Counter)
    for d in docs:
        p = pub.get(d["npi"])
        if p and p["email_type"] == "personal":
            for o in orgs(d):
                org_domains[o][p["email"].split("@")[1]] += 1

    def org_domain(d):
        best = None
        for o in orgs(d):  # клиника важнее больницы: список orgs начинается с клиник
            c = org_domains.get(o)
            if not c:
                continue
            dom, n = c.most_common(1)[0]
            if n >= MIN_COLLEAGUES and n / sum(c.values()) >= MIN_DOMAIN_SHARE:
                return dom, o[1]
        return best

    def usable_pattern(dom):
        p = pats.get(dom)
        if p and int(p["total_examples"]) >= MIN_PATTERN_EXAMPLES and float(p["share"]) >= MIN_PATTERN_SHARE:
            return p["top_pattern"], p
        return None, None

    stats = Counter()
    for d in docs:
        p = pub.get(d["npi"])
        d.update({"email": "", "email_status": "", "email_source": "", "email_note": "", "other_emails": ""})
        if p:
            d.update(email=p["email"], email_status="published_" + p["email_type"], email_source=p["email_source"],
                     other_emails=p["other_emails"], email_note=f"год публикации {p['email_year']}")
            stats[d["email_status"]] += 1
            if p["email_type"] == "personal":
                continue
        od = org_domain(d)
        if not od:
            continue
        dom, org = od
        pattern, prow = usable_pattern(dom)
        local = build(pattern, d) if pattern else None
        if not local:
            continue
        guess = f"{local}@{dom}"
        share = float(prow["share"])
        # точность по проверке на врачах с известным адресом: ≥0.9 → ~84%, 0.7–0.9 → ~66%, 0.5–0.7 → ~48%
        level = "high" if share >= 0.9 else "medium" if share >= 0.7 else "low"
        alts = []
        if level != "high":  # запасные варианты по следующим схемам домена — для сервиса проверки
            for alt in [x.split(":")[0] for x in prow["all_patterns"].split("; ")[1:3]]:
                if (a := build(alt, d)) and f"{a}@{dom}" != guess:
                    alts.append(f"{a}@{dom}")
        if d["email"]:  # был только общий ящик — личный адрес по схеме ставим основным, общий уходит в other_emails
            alts.append(d["email"])
        d["other_emails"] = "; ".join(filter(None, alts + [d["other_emails"]]))
        d.update(email=guess, email_status=f"pattern_{level}",
                 email_source=f"схема {pattern} домена {dom} ({prow['top_count']}/{prow['total_examples']} примеров)",
                 email_note=f"домен по коллегам из: {org}")
        stats[d["email_status"]] += 1

    cols = ["npi", "first_name", "middle_name", "last_name", "credentials", "specialty", "email", "email_status",
            "email_source", "email_note", "other_emails", "clinic", "hospitals", "address", "city", "state", "zip",
            "phone", "likely_active", "in_medicare", "drug_signal", "partd_onc_claims", "partd_top_onc_drugs"] + \
           [k for k in docs[0] if k.startswith("pharma_")] + ["all_onc_specialties", "gender", "medical_school", "grad_year", "nppes_last_update"]
    order = {"published_personal": 0, "pattern_high": 1, "pattern_medium": 2, "published_unverified_owner": 3, "pattern_low": 4, "published_research_office": 5, "": 6}
    docs.sort(key=lambda d: (order[d["email_status"]], d["drug_signal"] != "yes", d["state"], d["last_name"]))
    with open(OUT / "final_oncologists.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(docs)
    with_email = sum(1 for d in docs if d["email"])
    print(f"итог: {len(docs):,} врачей, с имейлом {with_email:,} ({with_email / len(docs):.0%})")
    for k, v in stats.most_common():
        print(f"  {k}: {v:,}")
    act = [d for d in docs if d["drug_signal"] == "yes"]
    print(f"  среди «работающих с лекарствами» ({len(act):,}): с имейлом {sum(1 for d in act if d['email']):,}")


if __name__ == "__main__":
    main()
