"""Этап 1: все онкологи «на лекарствах» из NPPES + клиника/больница из CMS Doctors & Clinicians.

Запуск:  python3 stage1_registry.py            (данные кладутся в ../data, результат в ../out)
Только стандартная библиотека Python. Нужно ~2 ГБ диска (zip NPPES читается без распаковки).
"""
import csv, io, json, re, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "out"
DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
csv.field_size_limit(sys.maxsize)

TAXONOMIES = {
    "207RX0202X": "Medical Oncology",
    "207RH0003X": "Hematology & Oncology",
    "207VX0201X": "Gynecologic Oncology",
    "2080P0207X": "Pediatric Hematology-Oncology",
    "207RH0000X": "Hematology",
}
NPPES_INDEX = "https://download.cms.gov/nppes/NPI_Files.html"
CMS_DATASET = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{}"
DAC_ID, AFFIL_ID, HOSP_ID = "mj5m-pzi6", "27ea-46a8", "xubh-q36u"


def download(url, dest):
    if dest.exists():
        return dest
    print(f"скачиваю {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def nppes_zip():
    html = urllib.request.urlopen(NPPES_INDEX).read().decode("utf-8", "ignore")
    links = re.findall(r'href="([^"]*NPPES_Data_Dissemination_[A-Za-z]+_\d{4}(?:_V2)?\.zip)"', html)
    if not links:
        sys.exit("не нашёл ссылку на полную выгрузку NPPES на " + NPPES_INDEX)
    url = links[0] if links[0].startswith("http") else "https://download.cms.gov/nppes/" + links[0].lstrip("./")
    return download(url, DATA / Path(url).name)


def cms_csv(dataset_id, name):
    meta = json.load(urllib.request.urlopen(CMS_DATASET.format(dataset_id)))
    return download(meta["distribution"][0]["downloadURL"], DATA / name)


def norm_header(h):
    return re.sub(r"[^a-z0-9]", "", h.lower())


def pick(row, *names):
    for n in names:
        v = row.get(norm_header(n))
        if v:
            return v.strip()
    return ""


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        head = [norm_header(h) for h in next(r)]
        for vals in r:
            yield dict(zip(head, vals))


def load_nppes():
    z = zipfile.ZipFile(nppes_zip())
    main = next(n for n in z.namelist() if re.match(r"npidata_pfile_\d+-\d+\.csv$", n))
    docs = {}
    with z.open(main) as raw:
        r = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"))
        head = next(r)
        ix = {h: i for i, h in enumerate(head)}
        tax_cols = [(ix[f"Healthcare Provider Taxonomy Code_{k}"], ix[f"Healthcare Provider Primary Taxonomy Switch_{k}"]) for k in range(1, 16)]
        g = lambda row, col: row[ix[col]].strip()
        for n, row in enumerate(r):
            if n % 1_000_000 == 0:
                print(f"  NPPES: {n:,} строк, онкологов {len(docs):,}")
            if row[ix["Entity Type Code"]] != "1" or g(row, "NPI Deactivation Date") and not g(row, "NPI Reactivation Date"):
                continue
            codes = [(row[c], row[p]) for c, p in tax_cols if row[c] in TAXONOMIES]
            if not codes:
                continue
            primary = next((c for c, p in codes if p == "Y"), codes[0][0])
            docs[g(row, "NPI")] = {
                "npi": g(row, "NPI"),
                "first_name": g(row, "Provider First Name").title(),
                "middle_name": g(row, "Provider Middle Name").title(),
                "last_name": g(row, "Provider Last Name (Legal Name)").title(),
                "credentials": g(row, "Provider Credential Text"),
                "gender": g(row, "Provider Sex Code") if "Provider Sex Code" in ix else g(row, "Provider Gender Code"),
                "specialty": TAXONOMIES[primary],
                "all_onc_specialties": "; ".join(sorted({TAXONOMIES[c] for c, _ in codes})),
                "address": " ".join(filter(None, [g(row, "Provider First Line Business Practice Location Address"), g(row, "Provider Second Line Business Practice Location Address")])),
                "city": g(row, "Provider Business Practice Location Address City Name").title(),
                "state": g(row, "Provider Business Practice Location Address State Name"),
                "zip": g(row, "Provider Business Practice Location Address Postal Code")[:5],
                "phone": g(row, "Provider Business Practice Location Address Telephone Number"),
                "nppes_last_update": g(row, "Last Update Date"),
            }
    return docs


def add_cms(docs):
    clinics = {}
    for row in read_rows(cms_csv(DAC_ID, "dac_national.csv")):
        npi = pick(row, "NPI")
        if npi in docs:
            d = docs[npi]
            clinics.setdefault(npi, set()).add(pick(row, "Facility Name", "org_nm"))
            d["cms_primary_specialty"] = pick(row, "pri_spec")
            d["medical_school"] = pick(row, "Med_sch")
            d["grad_year"] = pick(row, "Grd_yr")
            d.setdefault("cms_city", pick(row, "City/Town", "cty"))
            d.setdefault("cms_state", pick(row, "State", "st"))
    for npi, names in clinics.items():
        docs[npi]["clinic"] = "; ".join(sorted(n for n in names if n))

    hosp_names = {pick(r, "Facility ID", "Provider ID"): pick(r, "Facility Name", "Hospital Name")
                  for r in read_rows(cms_csv(HOSP_ID, "hospitals.csv"))}
    hosps = {}
    for row in read_rows(cms_csv(AFFIL_ID, "facility_affiliation.csv")):
        npi = pick(row, "NPI")
        if npi in docs and "hospital" in pick(row, "facility_type").lower():
            ccn = pick(row, "Facility Affiliations Certification Number")
            hosps.setdefault(npi, set()).add(hosp_names.get(ccn) or ccn)
    for npi, names in hosps.items():
        docs[npi]["hospitals"] = "; ".join(sorted(names))


def main():
    docs = load_nppes()
    print(f"онкологов в NPPES: {len(docs):,}")
    add_cms(docs)
    cols = ["npi", "first_name", "middle_name", "last_name", "credentials", "gender", "specialty",
            "all_onc_specialties", "cms_primary_specialty", "clinic", "hospitals", "address", "city",
            "state", "zip", "phone", "medical_school", "grad_year", "nppes_last_update"]
    out = OUT / "stage1_oncologists.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(docs.values(), key=lambda d: (d["state"], d["last_name"])))
    by_spec = {}
    for d in docs.values():
        by_spec[d["specialty"]] = by_spec.get(d["specialty"], 0) + 1
    print(f"готово: {out}")
    for s, n in sorted(by_spec.items(), key=lambda x: -x[1]):
        print(f"  {s}: {n:,}")
    print(f"  с клиникой (CMS): {sum(1 for d in docs.values() if d.get('clinic')):,}")
    print(f"  с больницей (CMS): {sum(1 for d in docs.values() if d.get('hospitals')):,}")


if __name__ == "__main__":
    main()
