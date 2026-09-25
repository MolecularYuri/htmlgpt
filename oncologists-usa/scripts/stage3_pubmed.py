"""Этап 3а: имейлы, которые врачи сами указали в своих статьях (PubMed, аффилиации авторов).

Для каждого онколога ищем его статьи за последние годы с американской аффилиацией, берём имейл
из аффилиации именно этого автора и принимаем его, только если аффилиация совпадает
с городом/штатом врача (защита от однофамильцев).

Вход: out/stage1_oncologists.csv. Выход: out/pubmed_emails.csv (+ кэш в data/pubmed_cache/).
Лимит NCBI: 3 запроса/с без ключа, 10/с с ключом (переменная окружения NCBI_API_KEY).
"""
import csv, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT, CACHE = ROOT / "out", ROOT / "data" / "pubmed_cache"
CACHE.mkdir(parents=True, exist_ok=True)
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
KEY = os.environ.get("NCBI_API_KEY", "")
PAUSE = 0.11 if KEY else 0.35
FROM_YEAR, BATCH, RETMAX = 2015, 8, 400

STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_last_call = [0.0]


def fold(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def call(endpoint, params):
    params = dict(params, tool="onc_contacts", **({"api_key": KEY} if KEY else {}))
    for attempt in range(5):
        wait = PAUSE - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        try:
            data = urllib.parse.urlencode(params).encode()
            return urllib.request.urlopen(EUTILS + endpoint, data=data, timeout=120).read()
        except Exception as e:
            print(f"  повтор {endpoint}: {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError(f"NCBI не отвечает: {endpoint}")


def search_term(d):
    first = re.sub(r"[^A-Za-z -]", "", d["first_name"]).strip()
    last = re.sub(r"[^A-Za-z -]", "", d["last_name"]).strip()
    return f'"{last} {first}"[fau]'


def fetch_batch(batch_id, docs):
    cache = CACHE / f"{batch_id}.xml"
    if cache.exists():
        return cache.read_bytes()
    term = "(" + " OR ".join(search_term(d) for d in docs) + f") AND (USA[ad] OR United States[ad]) AND {FROM_YEAR}:3000[dp]"
    ids = json.loads(call("esearch.fcgi", {"db": "pubmed", "term": term, "retmax": RETMAX, "sort": "pub_date", "retmode": "json"}))["esearchresult"]["idlist"]
    xml = call("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}) if ids else b"<PubmedArticleSet/>"
    cache.write_bytes(xml)
    return xml


def location_match(aff, d):
    a = aff.lower()
    city, state = d["city"].lower(), d["state"]
    return bool((city and city in a) or (state in STATES and STATES[state].lower() in a) or re.search(rf"\b{state}\b", aff))


def extract(xml, docs):
    by_name = {}
    for d in docs:
        by_name.setdefault((fold(d["last_name"]), fold(d["first_name"])), []).append(d)
    found = []
    root = ET.fromstring(xml)
    for art in root.iter("PubmedArticle"):
        pmid = art.findtext(".//PMID")
        year = art.findtext(".//PubDate/Year") or (art.findtext(".//PubDate/MedlineDate") or "")[:4]
        for au in art.iter("Author"):
            key = (fold(au.findtext("LastName") or ""), fold((au.findtext("ForeName") or "").split(" ")[0]))
            if key not in by_name:
                continue
            for aff in (x.text or "" for x in au.iter("Affiliation")):
                for email in EMAIL.findall(aff):
                    email = email.rstrip(".").lower()
                    for d in by_name[key]:
                        if location_match(aff, d):
                            found.append({"npi": d["npi"], "email": email, "pmid": pmid, "year": year,
                                          "affiliation": aff.replace("\n", " ")[:300],
                                          "name_in_email": "yes" if fold(d["last_name"])[:5] in fold(email.split("@")[0]) else "no"})
    return found


def main():
    docs = list(csv.DictReader(open(OUT / "stage1_oncologists.csv", encoding="utf-8")))
    docs.sort(key=lambda d: d["npi"])
    rows = []
    batches = [docs[i:i + BATCH] for i in range(0, len(docs), BATCH)]
    t0 = time.time()
    for i, b in enumerate(batches):
        rows += extract(fetch_batch(f"{b[0]['npi']}_{len(b)}", b), b)
        if i % 100 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(batches)} пачек, имейлов найдено {len({r['npi'] for r in rows}):,} врачей, {el/60:.0f} мин")
    with open(OUT / "pubmed_emails.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["npi", "email", "pmid", "year", "name_in_email", "affiliation"])
        w.writeheader()
        w.writerows(rows)
    print(f"готово: имейлы из PubMed у {len({r['npi'] for r in rows}):,} врачей из {len(docs):,}")


if __name__ == "__main__":
    main()
