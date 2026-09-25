"""Этап 2: кто из онкологов реально работает с лекарствами.

- Medicare Part D (by Provider and Drug): какие онкопрепараты врач выписывает.
- Open Payments (general + research): какие фармкомпании платили врачу, в каких исследованиях он PI.

Файлы CMS большие (Open Payments ~8 ГБ), поэтому читаем их потоком и не сохраняем на диск.
Вход: out/stage1_oncologists.csv. Выход: out/stage2_oncologists.csv.
"""
import csv, io, json, re, sys, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
csv.field_size_limit(sys.maxsize)

CMS_CATALOG = "https://data.cms.gov/data.json"
OP_CATALOG = "https://openpaymentsdata.cms.gov/api/1/metastore/schemas/dataset/items?show-reference-ids=false"

# Онкопрепараты в Part D (в основном пероральные) — по международному непатентованному названию.
ONC_SUFFIX = re.compile(r"(tinib|ciclib|parib|lisib|rafenib|metinib|zomib|lutamide|domide|degib|rasib|sertib|tuzumab|ximab|mumab|zumab)\b", re.I)
ONC_NAMES = re.compile(r"\b(" + "|".join("""
capecitabine temozolomide anastrozole letrozole exemestane tamoxifen fulvestrant toremifene abiraterone
enzalutamide apalutamide darolutamide bicalutamide flutamide nilutamide relugolix leuprolide goserelin degarelix
hydroxyurea mercaptopurine thioguanine methotrexate chlorambucil melphalan busulfan cyclophosphamide lomustine
procarbazine etoposide topotecan trifluridine tretinoin arsenic venetoclax lenalidomide pomalidomide thalidomide
everolimus megestrol mitotane vorinostat panobinostat selinexor ivosidenib enasidenib olutasidenib vorasidenib
midostaurin gilteritinib quizartinib glasdegib azacitidine decitabine ruxolitinib fedratinib pacritinib momelotinib
anagrelide imiquimod belzutifan tazemetostat elacestrant inavolisib capivasertib revumenib ziftomenib
""".split()) + r")\b", re.I)


def is_onc_drug(generic):
    return bool(ONC_NAMES.search(generic) or ONC_SUFFIX.search(generic))


def stream_csv(url):
    print(f"читаю {url}")
    r = urllib.request.urlopen(url)
    return csv.DictReader(io.TextIOWrapper(r, encoding="utf-8", errors="replace", newline=""))


def partd_url():
    cat = json.load(urllib.request.urlopen(CMS_CATALOG))
    ds = next(d for d in cat["dataset"] if d["title"] == "Medicare Part D Prescribers - by Provider and Drug")
    csvs = [x for x in ds["distribution"] if x.get("mediaType") == "text/csv"]
    return max(csvs, key=lambda x: x.get("title", ""))["downloadURL"]  # самый свежий год


def open_payments_urls():
    items = json.load(urllib.request.urlopen(OP_CATALOG))
    found = {}
    for d in items:
        m = re.match(r"(\d{4}) (General|Research) Payment Data$", d.get("title", ""))
        if m:
            url = d["distribution"][0]["data"]["downloadURL"] if "data" in d["distribution"][0] else d["distribution"][0]["downloadURL"]
            found.setdefault(m.group(2), {})[int(m.group(1))] = url
    latest = max(found["General"])
    return latest, found["General"][latest], found["Research"][latest]


def main():
    docs = {r["npi"]: r for r in csv.DictReader(open(OUT / "stage1_oncologists.csv", encoding="utf-8"))}

    onc_claims, all_claims, onc_drugs = Counter(), Counter(), defaultdict(Counter)
    for n, row in enumerate(stream_csv(partd_url())):
        if n % 5_000_000 == 0:
            print(f"  Part D: {n:,}")
        npi = row["Prscrbr_NPI"]
        if npi not in docs:
            continue
        claims = int(float(row["Tot_Clms"] or 0))
        all_claims[npi] += claims
        if is_onc_drug(row["Gnrc_Name"]):
            onc_claims[npi] += claims
            onc_drugs[npi][row["Gnrc_Name"].strip().lower()] += claims

    year, gen_url, res_url = open_payments_urls()
    paid, companies, pay_drugs = Counter(), defaultdict(Counter), defaultdict(Counter)
    for n, row in enumerate(stream_csv(gen_url)):
        if n % 5_000_000 == 0:
            print(f"  Open Payments general: {n:,}")
        npi = row["Covered_Recipient_NPI"]
        if npi not in docs:
            continue
        amt = float(row["Total_Amount_of_Payment_USDollars"] or 0)
        paid[npi] += amt
        companies[npi][row["Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name"].strip()] += amt
        if drug := row["Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1"].strip():
            pay_drugs[npi][drug.upper()] += amt

    studies, res_companies = defaultdict(set), defaultdict(Counter)
    for row in stream_csv(res_url):
        for k in range(1, 6):
            npi = row.get(f"Principal_Investigator_{k}_NPI", "")
            if npi in docs:
                studies[npi].add(row.get("ClinicalTrials_Gov_Identifier", "").strip() or row.get("Name_of_Study", "").strip()[:80])
                res_companies[npi][row["Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name"].strip()] += 1

    top = lambda c, k: "; ".join(x for x, _ in c.most_common(k) if x)
    for npi, d in docs.items():
        d["partd_total_claims"] = all_claims.get(npi, 0)
        d["partd_onc_claims"] = onc_claims.get(npi, 0)
        d["partd_top_onc_drugs"] = top(onc_drugs[npi], 5) if npi in onc_drugs else ""
        d[f"pharma_payments_{year}_usd"] = round(paid.get(npi, 0), 2)
        d["pharma_companies_n"] = len(companies[npi]) if npi in companies else 0
        d["pharma_top_companies"] = top(companies[npi], 3) if npi in companies else ""
        d["pharma_top_drugs"] = top(pay_drugs[npi], 5) if npi in pay_drugs else ""
        d["pharma_trials_pi_n"] = len(studies[npi]) if npi in studies else 0
        d["pharma_trials"] = "; ".join(sorted(s for s in studies[npi] if s)[:10]) if npi in studies else ""
        d["pharma_trial_sponsors"] = top(res_companies[npi], 3) if npi in res_companies else ""
        d["drug_signal"] = "yes" if (d["partd_onc_claims"] or paid.get(npi) or npi in studies) else "no"

    rows = list(docs.values())
    out = OUT / "stage2_oncologists.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"готово: {out}")
    print(f"  выписывают онкопрепараты (Part D): {sum(1 for d in rows if d['partd_onc_claims']):,}")
    print(f"  получали выплаты от фармы ({year}): {sum(1 for d in rows if d[f'pharma_payments_{year}_usd']):,}")
    print(f"  PI в исследованиях фармы ({year}): {sum(1 for d in rows if d['pharma_trials_pi_n']):,}")
    print(f"  есть хоть один сигнал «работает с лекарствами»: {sum(1 for d in rows if d['drug_signal'] == 'yes'):,} из {len(rows):,}")


if __name__ == "__main__":
    main()
