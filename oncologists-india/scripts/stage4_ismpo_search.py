"""Этап 4: адресный поиск статей для членов ISMPO, которых не нашли по названию отделения.

Для каждого такого члена: Europe PMC AUTH:"Фамилия И" AND AFF:India → статьи, где у этого автора
индийская аффилиация (в том же городе, если он указан в ISMPO). Берём аффилиацию, имейлы из неё
и докачиваем до 5 свежих полных текстов открытого доступа (ищем там имейл для переписки).

Вход: out/india_oncologists.csv (строки ISMPO без статей), выход: data/ismpo_search.jsonl
"""
import csv, json, re, time, urllib.parse, urllib.request
from pathlib import Path
from stage3_build import fold, parse_place, EMAIL, CITY_RE, CITY_ALIASES

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT, FT = ROOT / "data", ROOT / "out", ROOT / "data" / "fulltext"
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
UA = {"User-Agent": "onc-research-contacts/1.0"}


def get(url):
    for attempt in range(5):
        try:
            time.sleep(0.34)
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 ** attempt)
    return None


def main():
    todo = [r for r in csv.DictReader(open(OUT / "india_oncologists.csv", encoding="utf-8")) if r["ismpo_no"] and r["n_pubs"] == "0"]
    out = DATA / "ismpo_search.jsonl"
    done = {json.loads(l)["ismpo_no"] for l in open(out)} if out.exists() else set()
    print(f"членов ISMPO без статей: {len(todo)}, уже искали: {len(done)}")
    with open(out, "a") as f:
        for i, m in enumerate(todo):
            if m["ismpo_no"] in done:
                continue
            last, first = fold(m["last_name"]), fold(m["first_name"].split(" ")[0]) if m["first_name"] else ""
            if len(last) < 2 or not first:
                f.write(json.dumps({"ismpo_no": m["ismpo_no"], "hits": []}) + "\n")
                continue
            city_m = CITY_RE.findall(m["city"])
            city = CITY_ALIASES[city_m[-1].lower()] if city_m else ""
            q = f'AUTH:"{m["last_name"]} {first[0].upper()}" AND AFF:"India" AND PUB_YEAR:[2012 TO 2026]'
            page = get(API + "search?" + urllib.parse.urlencode({"query": q, "format": "json", "resultType": "core", "pageSize": 100}))
            hits = []
            for r in (json.loads(page)["resultList"]["result"] if page else []):
                for a in r.get("authorList", {}).get("author", []):
                    if fold(a.get("lastName")) != last:
                        continue
                    fn = fold((a.get("firstName") or "").split(" ")[0])
                    if fn and len(fn) > 1 and fn != first or (not fn and fold(a.get("initials", ""))[:1] != first[0]):
                        continue
                    affs = [x.get("affiliation", "") for x in a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])]
                    aff = next((x for x in affs if "india" in x.lower()), "")
                    if not aff:
                        continue
                    org, acity, state = parse_place(aff)
                    if city and acity and acity != city:
                        continue  # однофамилец из другого города
                    hits.append({"pmid": r.get("pmid", ""), "pmcid": r.get("pmcid", ""), "oa": r.get("isOpenAccess") == "Y",
                                 "year": int(r.get("pubYear") or 0), "first": a.get("firstName", ""), "last": a.get("lastName", ""),
                                 "aff": aff, "org": org, "city": acity, "state": state,
                                 "emails": [e.lower().rstrip(".") for e in EMAIL.findall(aff)]})
                    break
            hits.sort(key=lambda h: -h["year"])
            for h in [h for h in hits if h["oa"] and h["pmcid"]][:5]:
                p = FT / f"{h['pmcid']}.xml"
                if not p.exists():
                    x = get(API + f"{h['pmcid']}/fullTextXML")
                    if x:
                        p.write_bytes(x)
            f.write(json.dumps({"ismpo_no": m["ismpo_no"], "hits": hits}) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}")
    print("готово")


if __name__ == "__main__":
    main()
