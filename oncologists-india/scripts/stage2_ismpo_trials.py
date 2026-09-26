"""Этап: список членов ISMPO (публичная страница) и контакты индийских центров из ClinicalTrials.gov.

Выход: out/ismpo_members.csv (номер, имя, город), out/ctgov_india_contacts.csv (имя, имейл, центр, город, NCT).
"""
import csv, html, json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "out"
DATA.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "onc-research-contacts/1.0"}


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def ismpo():
    page = DATA / "ismpo_members.html"
    if not page.exists():
        page.write_bytes(fetch("https://www.ismpo.org/membership/members-list"))
    s = page.read_text(encoding="utf-8", errors="ignore")
    table = s[s.find("<table"):s.find("</table>")]
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", table, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) >= 2 and cells[0].isdigit():
            rows.append({"ismpo_no": cells[0], "name": re.sub(r"\s+", " ", cells[1]), "city": cells[2] if len(cells) > 2 else ""})
    with open(OUT / "ismpo_members.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["ismpo_no", "name", "city"])
        w.writeheader()
        w.writerows(rows)
    print(f"ISMPO: {len(rows)} членов")


def ctgov():
    cache = DATA / "ctgov_india.jsonl"
    if not cache.exists():
        params = {"query.cond": "cancer OR neoplasm OR tumor OR lymphoma OR leukemia OR myeloma",
                  "query.locn": "India", "fields": "NCTId,BriefTitle,LeadSponsorName,CentralContact,OverallOfficial,Location",
                  "pageSize": 1000, "format": "json"}
        token, n = None, 0
        with open(cache.with_suffix(".part"), "w") as f:
            while True:
                page = json.loads(fetch("https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(dict(params, **({"pageToken": token} if token else {})))))
                for st in page.get("studies", []):
                    f.write(json.dumps(st) + "\n")
                n += len(page.get("studies", []))
                token = page.get("nextPageToken")
                print(f"  ClinicalTrials.gov: {n:,}")
                if not token:
                    break
                time.sleep(0.5)
        cache.with_suffix(".part").rename(cache)
    rows, seen = [], set()
    for line in open(cache):
        ps = json.loads(line).get("protocolSection", {})
        nct = ps.get("identificationModule", {}).get("nctId", "")
        sponsor = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")
        clm = ps.get("contactsLocationsModule", {})
        india_locs = [l for l in clm.get("locations", []) if (l.get("country") or "") == "India"]
        contacts = [(c, l) for l in india_locs for c in l.get("contacts", [])]
        if india_locs and len(india_locs) == len(clm.get("locations", [])):  # исследование только в Индии
            contacts += [(c, india_locs[0]) for c in clm.get("centralContacts", [])]
        for c, loc in contacts:
            email = (c.get("email") or "").strip().lower()
            name = (c.get("name") or "").strip()
            if not name or (name, email) in seen:
                continue
            seen.add((name, email))
            rows.append({"name": name, "role": c.get("role", ""), "email": email, "phone": c.get("phone", ""),
                         "facility": loc.get("facility", ""), "city": loc.get("city", ""), "state": loc.get("state", ""),
                         "nct": nct, "sponsor": sponsor})
    with open(OUT / "ctgov_india_contacts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["name", "role", "email", "phone", "facility", "city", "state", "nct", "sponsor"])
        w.writeheader()
        w.writerows(rows)
    print(f"ClinicalTrials.gov: {len(rows)} контактов в индийских центрах, с имейлом {sum(1 for r in rows if r['email'])}")


if __name__ == "__main__":
    ismpo()
    ctgov()
