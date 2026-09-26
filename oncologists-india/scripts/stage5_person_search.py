"""Этап 5: адресный поиск имейла для каждого активного врача, у которого его пока нет.

Europe PMC: AUTH:"Фамилия И" AND AFF:"<город>" — все статьи врача в любых журналах. Берём:
- имейлы из его собственной аффилиации (PubMed);
- полные тексты открытого доступа, где он первый или последний автор (обычно это автор для переписки).
Выход: data/person_search.jsonl (pid → найденные имейлы).
"""
import csv, json, re, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from stage3_build import fold, fulltext_emails, EMAIL, CITY_RE, CITY_ALIASES

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT, FT = ROOT / "data", ROOT / "out", ROOT / "data" / "fulltext"
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
UA = {"User-Agent": "onc-research-contacts/1.0"}
lock = threading.Lock()


def pid(r):
    return f"{fold(r['last_name'])}|{fold(r['first_name'])}|{fold(r['city'])}|{r['ismpo_no']}"


def get(url):
    for attempt in range(5):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 ** attempt)
    return None


def city_of(text):
    m = CITY_RE.findall(text or "")
    return CITY_ALIASES[m[-1].lower()] if m else ""


def search(r):
    last, first = fold(r["last_name"]), fold(r["first_name"].split(" ")[0]) if r["first_name"] else ""
    city = city_of(r["city"])
    res = {"pid": pid(r), "emails": [], "latest_year": 0, "latest_aff": ""}
    if len(last) < 2 or not first or not city:
        return res
    city_terms = [k for k, v in CITY_ALIASES.items() if v == city and len(k) > 3][:4]
    q = f'AUTH:"{r["last_name"]} {first[0].upper()}" AND (' + " OR ".join(f'AFF:"{c}"' for c in city_terms) + ") AND PUB_YEAR:[2012 TO 2026]"
    page = get(API + "search?" + urllib.parse.urlencode({"query": q, "format": "json", "resultType": "core", "pageSize": 100, "sort": "P_PDATE_D desc"}))
    ft_todo = []
    for art in (json.loads(page)["resultList"]["result"] if page else []):
        authors = art.get("authorList", {}).get("author", [])
        for pos, a in enumerate(authors):
            if fold(a.get("lastName")) != last:
                continue
            fn = fold((a.get("firstName") or "").split(" ")[0])
            if (fn and len(fn) > 1 and fn != first) or (not fn and fold(a.get("initials", ""))[:1] != first[0]):
                continue
            affs = [x.get("affiliation", "") for x in a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])]
            aff = next((x for x in affs if city_of(x) == city), "")
            if not aff:
                continue
            year = int(art.get("pubYear") or 0)
            if year > res["latest_year"]:
                res["latest_year"], res["latest_aff"] = year, EMAIL.sub("", aff)[:250]
            for e in EMAIL.findall(aff):
                res["emails"].append((e.lower().rstrip("."), "pubmed_affiliation", year, art.get("pmid", "")))
            if art.get("isOpenAccess") == "Y" and art.get("pmcid") and pos in (0, len(authors) - 1):
                ft_todo.append((art["pmcid"], year))
            break
    for pmcid, year in ft_todo[:4]:
        p = FT / f"{pmcid}.xml"
        if not p.exists() and not (FT / f"{pmcid}.none").exists():
            x = get(API + f"{pmcid}/fullTextXML")
            (p if x else FT / f"{pmcid}.none").write_bytes(x or b"")
        for sur, giv, e, how in fulltext_emails(pmcid):
            if fold(sur) == last and fold(giv)[:1] == first[0]:
                res["emails"].append((e, "fulltext_" + how, year, pmcid))
    return res


def main():
    rows = [r for r in csv.DictReader(open(OUT / "india_oncologists.csv", encoding="utf-8"))
            if r["email_type"] not in ("published_personal",) and not r["possible_non_physician"]
            and (r["ismpo_no"] or (r["last_pub_year"].isdigit() and int(r["last_pub_year"]) >= 2016))]
    out = DATA / "person_search.jsonl"
    done = {json.loads(l)["pid"] for l in open(out)} if out.exists() else set()
    todo = [r for r in rows if pid(r) not in done]
    print(f"врачей для адресного поиска: {len(rows):,}, осталось: {len(todo):,}")
    t0, n_found = time.time(), 0
    with open(out, "a") as f, ThreadPoolExecutor(4) as pool:
        for i, res in enumerate(pool.map(search, todo)):
            with lock:
                f.write(json.dumps(res) + "\n")
                f.flush()
            n_found += bool(res["emails"])
            if i % 200 == 0:
                print(f"  {i:,}/{len(todo):,}, с имейлом {n_found:,}, {(time.time() - t0) / 60:.0f} мин")
    print("готово")


if __name__ == "__main__":
    main()
