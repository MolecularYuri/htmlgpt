"""Этап 3: собираем людей и имейлы из статей, ISMPO и ClinicalTrials.gov → одна строка на врача.

Вход: data/epmc_core.jsonl, data/fulltext/*.xml, out/ismpo_members.csv, out/ctgov_india_contacts.csv
Выход: out/india_oncologists.csv
"""
import csv, json, re, unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "out"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

DEPT_CLASSES = [
    ("Paediatric oncology / haematology", r"p(a)?ediatric (hemato|haemato|oncol|hematology|haematology)|medical and p(a)?ediatric|medical & p(a)?ediatric"),
    ("Haemato-oncology / BMT", r"ha?emato[- ]?oncol|hematolog(y|ic)[- ]oncol|haematolog(y|ical)[- ]oncol|bone marrow transplant|hematolymphoid|ha?ematological oncol"),
    ("Clinical haematology", r"clinical ha?ematolog"),
    ("Medical oncology", r"medical oncolog"),
]
NON_PHYSICIAN = re.compile(r"nursing|nurse|biostatist|statistic|clinical research secretariat|pharmacy|pharmacolog|molecular|laborator|"
                           r"\bactrec\b|scientist|physiotherap|psycholog|nutrition|dietetic|data manage|epidemiolog", re.I)
STATES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
          "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
          "Mizoram", "Nagaland", "Odisha", "Orissa", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
          "Uttar Pradesh", "Uttarakhand", "West Bengal", "Delhi", "New Delhi", "Jammu and Kashmir", "Jammu & Kashmir",
          "Chandigarh", "Puducherry", "Pondicherry", "Ladakh"]
STATE_ABBR = {"MH": "Maharashtra", "KA": "Karnataka", "TN": "Tamil Nadu", "TG": "Telangana", "TS": "Telangana", "AP": "Andhra Pradesh",
              "KL": "Kerala", "UP": "Uttar Pradesh", "WB": "West Bengal", "DL": "Delhi", "GJ": "Gujarat", "RJ": "Rajasthan",
              "HR": "Haryana", "PB": "Punjab", "MP": "Madhya Pradesh", "OR": "Odisha", "OD": "Odisha", "CG": "Chhattisgarh",
              "JH": "Jharkhand", "BR": "Bihar", "UK": "Uttarakhand", "HP": "Himachal Pradesh", "JK": "Jammu and Kashmir",
              "CH": "Chandigarh", "AS": "Assam", "GA": "Goa", "PY": "Puducherry"}
CITY_ALIASES = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru", "trivandrum": "Thiruvananthapuram",
                "thiruvananthapuram": "Thiruvananthapuram", "gurgaon": "Gurugram", "gurugram": "Gurugram", "bombay": "Mumbai",
                "calcutta": "Kolkata", "madras": "Chennai", "cochin": "Kochi", "kochi": "Kochi", "ernakulam": "Kochi",
                "pondicherry": "Puducherry", "puducherry": "Puducherry", "vizag": "Visakhapatnam", "visakhapatnam": "Visakhapatnam",
                "vishakhapatnam": "Visakhapatnam", "vishakapatnam": "Visakhapatnam", "allahabad": "Prayagraj", "prayagraj": "Prayagraj",
                "mysore": "Mysuru", "mysuru": "Mysuru", "mangalore": "Mangaluru", "mangaluru": "Mangaluru", "baroda": "Vadodara",
                "vadodara": "Vadodara", "calicut": "Kozhikode", "kozhikode": "Kozhikode", "trichy": "Tiruchirappalli",
                "tiruchirappalli": "Tiruchirappalli", "benares": "Varanasi", "banaras": "Varanasi", "varanasi": "Varanasi",
                "rohini": "New Delhi", "new delhi": "New Delhi", "delhi": "New Delhi", "noida": "Noida", "greater noida": "Noida",
                "navi mumbai": "Navi Mumbai", "kharghar": "Navi Mumbai", "thane": "Thane", "secunderabad": "Hyderabad", "faridabad": "Faridabad",
                "ghaziabad": "Ghaziabad", "mohali": "Mohali", "sahibzada ajit singh nagar": "Mohali", "panchkula": "Panchkula",
                "gauhati": "Guwahati", "guwahati": "Guwahati", "cuttack": "Cuttack", "manipal": "Manipal", "belgaum": "Belagavi",
                "belagavi": "Belagavi", "hubli": "Hubballi", "hubballi": "Hubballi", "thrissur": "Thrissur", "trichur": "Thrissur",
                "kottayam": "Kottayam", "kollam": "Kollam", "kannur": "Kannur", "tellicherry": "Thalassery", "thalassery": "Thalassery",
                "coimbatore": "Coimbatore", "madurai": "Madurai", "salem": "Salem", "vellore": "Vellore", "kanchipuram": "Kanchipuram",
                "tirupati": "Tirupati", "vijayawada": "Vijayawada", "guntur": "Guntur", "nellore": "Nellore", "warangal": "Warangal",
                "ahmedabad": "Ahmedabad", "surat": "Surat", "rajkot": "Rajkot", "gandhinagar": "Gandhinagar", "jamnagar": "Jamnagar",
                "pune": "Pune", "nagpur": "Nagpur", "nashik": "Nashik", "aurangabad": "Chhatrapati Sambhajinagar", "sangli": "Sangli",
                "miraj": "Miraj", "kolhapur": "Kolhapur", "wardha": "Wardha", "sevagram": "Wardha", "barshi": "Barshi", "solapur": "Solapur",
                "jaipur": "Jaipur", "jodhpur": "Jodhpur", "bikaner": "Bikaner", "udaipur": "Udaipur", "ajmer": "Ajmer", "kota": "Kota",
                "lucknow": "Lucknow", "kanpur": "Kanpur", "agra": "Agra", "meerut": "Meerut", "gorakhpur": "Gorakhpur", "aligarh": "Aligarh",
                "bareilly": "Bareilly", "jhansi": "Jhansi", "patna": "Patna", "muzaffarpur": "Muzaffarpur", "ranchi": "Ranchi",
                "jamshedpur": "Jamshedpur", "dhanbad": "Dhanbad", "bhubaneswar": "Bhubaneswar", "bhubaneshwar": "Bhubaneswar",
                "berhampur": "Berhampur", "burla": "Burla", "sambalpur": "Sambalpur", "raipur": "Raipur", "bilaspur": "Bilaspur",
                "bhopal": "Bhopal", "indore": "Indore", "gwalior": "Gwalior", "jabalpur": "Jabalpur", "chandigarh": "Chandigarh",
                "ludhiana": "Ludhiana", "amritsar": "Amritsar", "patiala": "Patiala", "bathinda": "Bathinda", "jalandhar": "Jalandhar",
                "faridkot": "Faridkot", "shimla": "Shimla", "dehradun": "Dehradun", "rishikesh": "Rishikesh", "haldwani": "Haldwani",
                "srinagar": "Srinagar", "jammu": "Jammu", "kolkata": "Kolkata", "siliguri": "Siliguri", "durgapur": "Durgapur",
                "hyderabad": "Hyderabad", "chennai": "Chennai", "mumbai": "Mumbai", "karad": "Karad", "davangere": "Davanagere",
                "davanagere": "Davanagere", "kolar": "Kolar", "tumkur": "Tumakuru", "gulbarga": "Kalaburagi", "kalaburagi": "Kalaburagi",
                "dibrugarh": "Dibrugarh", "silchar": "Silchar", "imphal": "Imphal", "shillong": "Shillong", "agartala": "Agartala",
                "aizawl": "Aizawl", "gangtok": "Gangtok", "goa": "Goa", "panaji": "Goa", "bambolim": "Goa", "margao": "Goa",
                "puttaparthi": "Puttaparthi", "karamsad": "Karamsad", "nadiad": "Nadiad", "loni": "Loni", "sawangi": "Wardha",
                "kalyani": "Kalyani", "muzaffarnagar": "Muzaffarnagar", "saifai": "Saifai", "mangalagiri": "Mangalagiri",
                "bibinagar": "Bibinagar", "jodhpur aiims": "Jodhpur", "deoghar": "Deoghar", "bathinda aiims": "Bathinda",
                "darbhanga": "Darbhanga", "gorakhpur aiims": "Gorakhpur", "kalpetta": "Kalpetta", "perinthalmanna": "Perinthalmanna",
                "tirunelveli": "Tirunelveli", "thanjavur": "Thanjavur", "puttur": "Puttur", "karaikal": "Karaikal", "mandya": "Mandya"}
CITY_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITY_ALIASES), key=len, reverse=True)) + r")\b", re.I)
ORG_WORDS = re.compile(r"hospital|institute|centre|center|college|university|aiims|memorial|clinic|foundation|pgimer|"
                       r"medical sciences|health|research|trust|cmc|jipmer|sgpgi", re.I)
DEPT_WORDS = re.compile(r"department|dept|division|unit|section|service|oncology|haematology|hematology", re.I)


def fold(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


OTHER_DEPT = re.compile(r"patholog|radiodiagnos|radiology|radiation|radiotherap|surg|microbiolog|biochem|anatomy|physiology|"
                        r"community medicine|anaesthe|anesthe|nuclear medicine|transfusion|gyn|obstet|ent\b|dermatolog", re.I)


def split_affs(aff):
    """Europe PMC склеивает несколько аффилиаций в одну строку — режем на отдельные учреждения."""
    parts = re.split(r";|\s(?=\d\s?[A-Z])|(?<=India)\.\s|(?<=India),\s(?=[A-Z])", aff)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def dept_class(aff):
    """(класс отделения, кусок аффилиации, смешанное ли отделение) или None."""
    for part in split_affs(aff):
        a = part.lower()
        if "india" not in a:
            continue
        for name, pat in DEPT_CLASSES:
            if re.search(pat, a):
                head = a.split(",")[0]
                mixed = bool(re.match(r"\W*(a |b |c )?departments\b", head) and OTHER_DEPT.search(head))
                return name, part, mixed
    return None


def parse_place(aff):
    aff = EMAIL.sub("", aff)
    aff = re.sub(r"(electronic address|e-?mail|email)\s*:?", "", aff, flags=re.I)
    segs = [s.strip(" .;") for s in re.split(r"[,;]", aff) if s.strip(" .;")]
    state = next((st for st in STATES if st.lower() in aff.lower()), "")
    for s in segs:
        if s.upper() in STATE_ABBR and not state:
            state = STATE_ABBR[s.upper()]
    state = {"New Delhi": "Delhi", "Orissa": "Odisha", "Pondicherry": "Puducherry", "Jammu & Kashmir": "Jammu and Kashmir"}.get(state, state)
    org = next((s for s in segs if ORG_WORDS.search(s) and not re.match(r"(department|dept|division)\b", s, re.I)), "")
    found = CITY_RE.findall(aff)
    if found:
        city = CITY_ALIASES[found[-1].lower()]
        if city == "New Delhi" and len(found) > 1 and CITY_ALIASES[found[-2].lower()] not in ("New Delhi",):
            city = CITY_ALIASES[found[-2].lower()] if found[-2].lower() in ("noida", "gurugram", "gurgaon", "faridabad", "ghaziabad") else city
        return org[:120], city, state
    city = ""
    for s in reversed(segs):
        t = re.sub(r"\b\d{6}\b|\b\d{3}\s?\d{3}\b", "", s).strip(" -")
        if not t or t.lower() == "india" or t in STATES or t.upper() in STATE_ABBR or ORG_WORDS.search(t) or DEPT_WORDS.search(t) or len(t) > 30:
            continue
        city = t
        break
    if city.lower() == "new delhi":
        city = "New Delhi"
    return org[:120], city, state


def author_key(last, first, initials):
    l = fold(last)
    f = fold((first or "").split(" ")[0]) if first and len(fold((first or "").split(" ")[0])) > 1 else ""
    return l, f, fold(initials)[:1] or (f[:1] if f else "")


# ---------- 1. кандидаты из метаданных ----------
def load_candidates():
    recs = []
    for line in open(DATA / "epmc_core.jsonl"):
        r = json.loads(line)
        year = int(r.get("pubYear") or 0)
        for a in r.get("authorList", {}).get("author", []):
            affs = [x.get("affiliation", "") for x in a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])]
            for full_aff in affs:
                dc = dept_class(full_aff)
                if not dc:
                    continue
                dc, aff, mixed = dc
                org, city, state = parse_place(aff)
                recs.append({"pmid": r.get("pmid", ""), "pmcid": r.get("pmcid", ""), "year": year,
                             "last": a.get("lastName", ""), "first": a.get("firstName", ""), "initials": a.get("initials", ""),
                             "key": author_key(a.get("lastName"), a.get("firstName"), a.get("initials")),
                             "dept": dc, "aff": aff, "org": org, "city": city, "state": state,
                             "non_physician": bool(NON_PHYSICIAN.search(aff)), "mixed": mixed,
                             "emails": [e.lower().rstrip(".") for e in EMAIL.findall(full_aff)]})
                break
    return recs


# ---------- 2. имейлы из полных текстов ----------
def fulltext_emails(pmcid):
    """[(surname, given, email, how)] — имейлы, которые удалось привязать к конкретному автору статьи."""
    p = DATA / "fulltext" / f"{pmcid}.xml"
    if not p.exists():
        return []
    try:
        root = ET.fromstring(re.sub(rb"<!DOCTYPE[^>]*>", b"", p.read_bytes()))
    except ET.ParseError:
        return []
    text = lambda el: " ".join(el.itertext()) if el is not None else ""
    corresp = {c.get("id"): text(c) for c in root.iter("corresp")}
    authors = []
    for c in root.iter("contrib"):
        if c.get("contrib-type") not in (None, "author"):
            continue
        n = c.find(".//name")
        if n is None:
            continue
        sur, giv = n.findtext("surname") or "", n.findtext("given-names") or ""
        own = [e for el in c.iter("email") for e in EMAIL.findall(text(el) or "")]
        refs = [x.get("rid") for x in c.iter("xref") if x.get("ref-type") == "corresp"]
        authors.append({"sur": sur, "giv": giv, "own": own, "refs": refs, "is_corr": c.get("corresp") == "yes" or bool(refs)})
    out = []
    for a in authors:
        for e in a["own"]:
            out.append((a["sur"], a["giv"], e, "author_tag"))
    all_corr_emails = {e for t in corresp.values() for e in EMAIL.findall(t)} | {e for el in root.iter("author-notes") for e in EMAIL.findall(text(el))}
    assigned = {e for _, _, e, _ in out}
    for e in sorted(all_corr_emails - assigned):
        local = fold(e.split("@")[0])
        # 1) фамилия/имя в адресе
        by_name = [a for a in authors if (len(fold(a["sur"])) >= 4 and fold(a["sur"]) in local) or
                   (len(fold(a["giv"].split(" ")[0])) >= 4 and fold(a["giv"].split(" ")[0]) in local)]
        if len(by_name) == 1:
            out.append((by_name[0]["sur"], by_name[0]["giv"], e, "corresp_name_in_email"))
            continue
        # 2) единственный автор для переписки
        corr = [a for a in authors if a["is_corr"]]
        if len(corr) == 1 and len(all_corr_emails - assigned) == 1:
            out.append((corr[0]["sur"], corr[0]["giv"], e, "corresp_single"))
            continue
        # 3) фамилия автора упомянута в тексте блока corresp, где стоит этот имейл
        blocks = [t for t in corresp.values() if e in t]
        named = [a for a in authors if blocks and len(fold(a["sur"])) >= 3 and any(a["sur"] and a["sur"] in b for b in blocks)]
        if len(named) == 1:
            out.append((named[0]["sur"], named[0]["giv"], e, "corresp_text"))
    return [(s, g, e.lower().rstrip("."), how) for s, g, e, how in out]


# ---------- 3. склейка людей ----------
def cluster(recs):
    full = defaultdict(list)   # (last, first) → записи
    initial_only = []
    for r in recs:
        l, f, i = r["key"]
        if not l:
            continue
        (full[(l, f)] if f else initial_only).append(r)
    people = []
    for (l, f), rs in full.items():
        # делим однофамильцев по городам; части с общим имейлом снова склеиваем
        by_city = defaultdict(list)
        for r in rs:
            by_city[fold(r["city"]) or "?"].append(r)
        groups = list(by_city.values())
        merged = True
        while merged:
            merged = False
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    ei = {e for r in groups[i] for e in r["emails"]}
                    ej = {e for r in groups[j] for e in r["emails"]}
                    unknown = any(fold(r["city"]) == "" for r in groups[i] + groups[j]) and (len(groups[i]) == 1 or len(groups[j]) == 1)
                    if (ei & ej) or unknown:
                        groups[i] += groups.pop(j)
                        merged = True
                        break
                if merged:
                    break
        people += groups
    # записи только с инициалом — к единственному подходящему человеку в том же городе
    index = defaultdict(list)
    for p in people:
        l, f, _ = p[0]["key"]
        index[(l, f[:1])].append(p)
    for r in initial_only:
        l, _, i = r["key"]
        cands = [p for p in index.get((l, i), []) if fold(r["city"]) in {fold(x["city"]) for x in p}]
        if len(cands) == 1:
            cands[0].append(r)
        else:
            people.append([r])
    return people


def summarize(p):
    p.sort(key=lambda r: -r["year"])
    latest = p[0]
    best_name = max(p, key=lambda r: (len(r["first"] or ""), r["year"]))
    emails = Counter()
    email_info = {}
    for r in p:
        for e, how in [(e, "pubmed_affiliation") for e in r["emails"]] + r.get("ft_emails", []):
            emails[e] += 1
            if e not in email_info or r["year"] > email_info[e][1]:
                email_info[e] = (how, r["year"], r["pmid"] or r["pmcid"])
    return {
        "first_name": best_name["first"], "last_name": best_name["last"],
        "specialty": Counter(r["dept"] for r in p).most_common(1)[0][0],
        "institution": latest["org"] or next((r["org"] for r in p if r["org"]), ""),
        "city": latest["city"] or next((r["city"] for r in p if r["city"]), ""),
        "state": latest["state"] or next((r["state"] for r in p if r["state"]), ""),
        "last_pub_year": latest["year"], "n_pubs": len({r["pmid"] or r["pmcid"] for r in p}),
        "possible_non_physician": "yes" if sum(r["non_physician"] for r in p) > len(p) / 2 else "",
        "specialty_unclear": "yes" if sum(r["mixed"] for r in p) > len(p) / 2 else "",
        "latest_affiliation": EMAIL.sub("", latest["aff"])[:250],
        "sample_pmids": "; ".join(sorted({r["pmid"] for r in p if r["pmid"]})[:5]),
        "_emails": emails, "_email_info": email_info, "_records": p,
    }


def match_name(name):
    n = re.sub(r"\b(dr|prof|col|brig|maj|major|lt|gen|md|dm|mbbs)\b\.?|[().]", " ", name, flags=re.I)
    parts = [x for x in re.split(r"[\s,]+", n) if x]
    if len(parts) < 2:
        return None
    return fold(parts[-1]), fold(parts[0])


def main():
    recs = load_candidates()
    print(f"записей автор×статья из индийских онкоотделений: {len(recs):,}")
    by_article = defaultdict(list)
    for r in recs:
        by_article[r["pmcid"]].append(r)
    n_ft = 0
    for pmcid, rs in by_article.items():
        if not pmcid:
            continue
        for sur, giv, e, how in fulltext_emails(pmcid):
            k = author_key(sur, giv, giv[:1])
            for r in rs:
                if r["key"][0] == k[0] and (not k[1] or not r["key"][1] or r["key"][1] == k[1]) and r["key"][2] == k[2]:
                    r.setdefault("ft_emails", []).append((e, "fulltext_" + how))
                    n_ft += 1
    print(f"имейлов из полных текстов привязано к авторам: {n_ft:,}")

    people = [summarize(p) for p in cluster(recs)]

    # ISMPO
    ismpo = list(csv.DictReader(open(OUT / "ismpo_members.csv", encoding="utf-8")))
    idx = defaultdict(list)
    for p in people:
        idx[(fold(p["last_name"]), fold(p["first_name"].split(" ")[0]))].append(p)
        idx[(fold(p["last_name"]), fold(p["first_name"])[:1])].append(p)
    matched = found_by_search = 0
    sp = DATA / "ismpo_search.jsonl"
    ismpo_hits = {j["ismpo_no"]: j["hits"] for j in map(json.loads, open(sp))} if sp.exists() else {}
    for m in ismpo:
        key = match_name(m["name"])
        cands = (idx.get(key, []) or idx.get((key[0], key[1][:1]), [])) if key else []
        if len(cands) > 1:
            cands = [p for p in cands if fold(m["city"])[:5] and fold(m["city"])[:5] in fold(p["city"] + p["latest_affiliation"])] or cands
        if len(cands) == 1:
            cands[0]["ismpo_no"] = m["ismpo_no"]
            matched += 1
        elif ismpo_hits.get(m["ismpo_no"]):
            # нашли статьи адресным поиском (этап 4) — строим человека из них
            recs_m = []
            for h in ismpo_hits[m["ismpo_no"]]:
                r = {"pmid": h["pmid"], "pmcid": h["pmcid"], "year": h["year"], "last": h["last"], "first": h["first"],
                     "initials": "", "key": author_key(h["last"], h["first"], h["first"][:1]),
                     "dept": "Medical / paediatric oncology (ISMPO member)", "aff": h["aff"], "org": h["org"],
                     "city": h["city"], "state": h["state"], "non_physician": False, "mixed": False, "emails": h["emails"]}
                if h["pmcid"]:
                    for sur, giv, e, how in fulltext_emails(h["pmcid"]):
                        if fold(sur) == r["key"][0] and fold(giv)[:1] == r["key"][2]:
                            r.setdefault("ft_emails", []).append((e, "fulltext_" + how))
                recs_m.append(r)
            p = summarize(recs_m)
            p["ismpo_no"] = m["ismpo_no"]
            people.append(p)
            found_by_search += 1
        else:
            parts = re.sub(r"^\s*dr\.?\s+", "", m["name"], flags=re.I).split()
            people.append({"first_name": " ".join(parts[:-1]), "last_name": parts[-1] if parts else m["name"],
                           "specialty": "Medical / paediatric oncology (ISMPO member)", "institution": "", "city": m["city"],
                           "state": "", "last_pub_year": "", "n_pubs": 0, "possible_non_physician": "", "specialty_unclear": "",
                           "latest_affiliation": "", "sample_pmids": "", "ismpo_no": m["ismpo_no"],
                           "_emails": Counter(), "_email_info": {}, "_records": []})
    print(f"ISMPO: сопоставлено со статьями {matched} из {len(ismpo)}; найдено адресным поиском ещё {found_by_search}")

    # ClinicalTrials.gov
    ct_added = 0
    idx2 = defaultdict(list)
    for p in people:
        idx2[(fold(p["last_name"]), fold(p["first_name"].split(" ")[0]))].append(p)
    for c in csv.DictReader(open(OUT / "ctgov_india_contacts.csv", encoding="utf-8")):
        key = match_name(re.sub(r",.*$", "", c["name"]))
        if not key or not c["email"]:
            continue
        cands = idx2.get(key, [])
        if len(cands) > 1:
            cands = [p for p in cands if fold(c["city"])[:5] and fold(c["city"])[:5] in fold(p["city"] + p["latest_affiliation"])] or []
        if len(cands) == 1:
            p = cands[0]
            p["_emails"][c["email"]] += 1
            p["_email_info"].setdefault(c["email"], ("clinicaltrials_contact", 2026, c["nct"]))
            ct_added += 1
    print(f"ClinicalTrials.gov: имейлов добавлено к известным врачам {ct_added}")

    rows = []
    for p in people:
        emails = p["_emails"]
        info = p["_email_info"]
        last = fold(p["last_name"])
        first = fold(p["first_name"].split(" ")[0]) if p["first_name"] else ""

        def score(e):
            local = fold(e.split("@")[0])
            named = (len(last) >= 3 and last in local) or (len(first) >= 3 and first in local)
            how = info[e][0]
            return (named, how.startswith("fulltext_author_tag") or how.startswith("fulltext_corresp") or how == "pubmed_affiliation",
                    info[e][1], emails[e])
        ranked = sorted(emails, key=score, reverse=True)
        best = ranked[0] if ranked else ""
        if best:
            local = fold(best.split("@")[0])
            named = (len(last) >= 3 and last in local) or (len(first) >= 3 and first in local)
            etype = "published_personal" if named else "published_unverified_owner"
            if info[best][0] == "clinicaltrials_contact":
                etype = "trial_contact" if named else "trial_contact_generic"
        else:
            etype = ""
        rows.append({k: v for k, v in p.items() if not k.startswith("_")} | {
            "email": best, "email_type": etype,
            "email_source": f"{info[best][0]}:{info[best][2]}" if best else "",
            "email_year": info[best][1] if best else "",
            "other_emails": "; ".join(ranked[1:4]),
        })
    rows.sort(key=lambda r: (r["email_type"] != "published_personal", -int(r["last_pub_year"] or 0), r["last_name"]))
    cols = ["first_name", "last_name", "specialty", "institution", "city", "state", "email", "email_type", "email_source",
            "email_year", "other_emails", "last_pub_year", "n_pubs", "ismpo_no", "possible_non_physician", "specialty_unclear",
            "latest_affiliation", "sample_pmids"]
    with open(OUT / "india_oncologists.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    t = Counter(r["email_type"] or "(нет)" for r in rows)
    print(f"людей: {len(rows):,}; с имейлом: {sum(1 for r in rows if r['email']):,}  {dict(t)}")
    rec = [r for r in rows if r["last_pub_year"] and int(r["last_pub_year"]) >= 2020 and not r["possible_non_physician"]]
    print(f"  публиковались с 2020 и не помечены как не-врачи: {len(rec):,}, из них с имейлом {sum(1 for r in rec if r['email']):,}")


if __name__ == "__main__":
    main()
