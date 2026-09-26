"""Этап 1–2: статьи индийских отделений медицинской онкологии / онкогематологии / детской онкологии.

1. Europe PMC search (resultType=core) — все статьи с такими аффилиациями → data/epmc_core.jsonl
2. Для статей в открытом доступе — полный текст (JATS XML) → data/fulltext/<PMCID>.xml

Europe PMC API открытый; держим ~3 запроса/с. Повторный запуск докачивает только недостающее.
"""
import json, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FT = DATA / "fulltext"
FT.mkdir(parents=True, exist_ok=True)
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
PAUSE = 0.34

DEPTS = ['"medical oncology"', '"haemato-oncology"', '"hemato-oncology"', '"hematology-oncology"',
         '"haematology-oncology"', '"hematologic oncology"', '"haematological oncology"', '"pediatric oncology"',
         '"paediatric oncology"', '"pediatric hematology"', '"paediatric haematology"', '"clinical hematology"',
         '"clinical haematology"', '"bone marrow transplant"', '"adult hematolymphoid"', '"hemato oncology"',
         '"haemato oncology"', '"medical and pediatric oncology"', '"medical & pediatric oncology"']
QUERY = 'AFF:"India" AND (' + " OR ".join(f"AFF:{d}" for d in DEPTS) + ") AND PUB_YEAR:[2014 TO 2026]"

_last = [0.0]


def get(url, params=None, as_json=True):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        wait = PAUSE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "onc-research-contacts/1.0"}), timeout=120).read()
            return json.loads(raw) if as_json else raw
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  повтор ({e.code}) {url[:90]}")
        except Exception as e:
            print(f"  повтор ({e}) {url[:90]}")
        time.sleep(2 ** attempt)
    raise RuntimeError("Europe PMC не отвечает")


def harvest_metadata():
    out = DATA / "epmc_core.jsonl"
    if out.exists():
        print(f"метаданные уже скачаны: {out}")
        return out
    tmp, cursor, n = out.with_suffix(".part"), "*", 0
    with open(tmp, "w") as f:
        while True:
            page = get(API + "search", {"query": QUERY, "format": "json", "resultType": "core", "pageSize": 1000, "cursorMark": cursor})
            results = page["resultList"]["result"]
            for r in results:
                f.write(json.dumps(r) + "\n")
            n += len(results)
            print(f"  метаданные: {n:,} / {page['hitCount']:,}")
            nxt = page.get("nextCursorMark")
            if not results or not nxt or nxt == cursor:
                break
            cursor = nxt
    tmp.rename(out)
    return out


def harvest_fulltext(meta):
    ids = [r["pmcid"] for r in map(json.loads, open(meta)) if r.get("isOpenAccess") == "Y" and r.get("pmcid")]
    todo = [p for p in ids if not (FT / f"{p}.xml").exists() and not (FT / f"{p}.none").exists()]
    print(f"полных текстов в открытом доступе: {len(ids):,}, докачать: {len(todo):,}")
    def one(pmcid):
        x = get_nopause(API + f"{pmcid}/fullTextXML")
        (FT / (f"{pmcid}.xml" if x else f"{pmcid}.none")).write_bytes(x or b"")

    # 4 параллельных запроса: ответ на полный текст идёт 2–8 с, последовательно это часы
    with ThreadPoolExecutor(4) as pool:
        for i, _ in enumerate(pool.map(one, todo)):
            if i % 250 == 0:
                print(f"  полные тексты: {i:,} / {len(todo):,}")


def get_nopause(url):
    for attempt in range(6):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "onc-research-contacts/1.0"}), timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  повтор ({e.code}) {url[:90]}")
        except Exception as e:
            print(f"  повтор ({e}) {url[:90]}")
        time.sleep(2 ** attempt)
    return None


if __name__ == "__main__":
    harvest_fulltext(harvest_metadata())
    print("готово")
