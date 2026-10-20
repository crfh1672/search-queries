#!/usr/bin/env python3
"""בדיקות תקינות לכל מערכי השאילתות ב-datasets/.

כל תיקיית מערך חייבת להכיל:
    queries.jsonl   המקור לעבודה
    queries.csv     אותם נתונים לפתיחה באקסל (נגזר מה-JSONL, חייב להיות זהה לו)
    source.json     שם המסכת, קידומת id, ומקור הטקסט: קומיט קבוע, נתיב ו-sha256 של הקובץ בספריית אוצריא

הטקסט עצמו לא נשמר במאגר. הבודק מושך אותו מהקומיט הקבוע (או משתמש במטמון ב-.cache/) ובודק מולו.

שימוש:
    python tools/validate.py                  # בודק את כל המערכים
    python tools/validate.py datasets/taanit  # בודק מערך אחד
    python tools/validate.py --offline        # רק מהמטמון, בלי רשת
קוד יציאה 1 אם נמצאה בעיה.
"""
import csv, hashlib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import library

FIELDS = ["id", "query", "type", "correct_ref", "correct_quote", "correct_line",
          "near_miss_ref", "near_miss_quote", "near_miss_line",
          "near_miss_same_amud", "split", "verified_by_human"]
OPTIONAL_EMPTY = {"verified_by_human"}
TYPES = {"conceptual", "short"}
SPLITS = {"test", "train"}
YESNO = {"כן", "לא"}
META_KEYS = {"masechet", "id_prefix", "origin_repo", "origin_path",
             "origin_commit", "origin_sha256", "note"}
LINE_RE = re.compile(r"^\d+(-\d+)?$")
HEADER_RE = re.compile(r'^\s*דף ([א-ת"״׳\']+)([.:])\s*$')


def amud_ranges(lines):
    """(אותיות הדף, 'א'/'ב') -> (שורה ראשונה, שורה אחרונה), מספור מ-1."""
    heads = []
    for i, l in enumerate(lines):
        m = HEADER_RE.match(l)
        if m:
            heads.append((i + 1, m.group(1), "א" if m.group(2) == "." else "ב"))
    out = {}
    for k, (ln, daf, amud) in enumerate(heads):
        end = heads[k + 1][0] - 1 if k + 1 < len(heads) else len(lines)
        out[(daf, amud)] = (ln, end)
    return out


def parse_ref(ref, masechet):
    m = re.fullmatch(re.escape(masechet) + r' ([א-ת]+) ע"([אב])', ref)
    return (m.group(1), m.group(2)) if m else None


def span(s):
    a, _, b = s.partition("-")
    return int(a), int(b or a)


def validate_dataset(d, loader=None, offline=False):
    """loader(d, meta) -> (bytes, error) מאפשר לבדיקות להחליף את המשיכה מהספרייה."""
    errs = []
    def err(msg): errs.append(f"{d}: {msg}")

    need = ["queries.jsonl", "queries.csv", "source.json"]
    for n in need:
        if not os.path.isfile(os.path.join(d, n)):
            err(f"חסר הקובץ {n}")
    if errs:
        return errs

    # --- source.json ---
    try:
        with open(os.path.join(d, "source.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return [f"{d}/source.json: JSON לא תקין ({e})"]
    if set(meta) != META_KEYS:
        err(f"source.json: מפתחות לא תקינים. חסרים {sorted(META_KEYS - set(meta))}, מיותרים {sorted(set(meta) - META_KEYS)}")
        return errs
    if not (isinstance(meta.get("origin_commit"), str) and re.fullmatch(r"[0-9a-f]{40}", meta["origin_commit"])):
        err("source.json: origin_commit חייב להיות SHA מלא של קומיט (40 תווים)")
        return errs
    if loader is None:
        slug = os.path.basename(os.path.normpath(d))
        data, why = library.get_pinned(slug, meta, offline)
    else:
        data, why = loader(d, meta)
    if why:
        err(f"קובץ הספרייה: {why}")
        return errs
    if hashlib.sha256(data).hexdigest() != meta["origin_sha256"]:
        err("קובץ הספרייה שונה מ-origin_sha256 שב-source.json")
        return errs
    lines = [library.norm(l.rstrip("\r")) for l in data.decode("utf-8").split("\n")]
    ranges = amud_ranges(lines)
    masechet, prefix = meta["masechet"], meta["id_prefix"]

    # --- JSONL ---
    rows = []
    with open(os.path.join(d, "queries.jsonl"), "rb") as f:
        data = f.read()
    if data.startswith(b"\xef\xbb\xbf"):
        err("queries.jsonl: אסור BOM")
    if data and not data.endswith(b"\n"):
        err("queries.jsonl: חסר מעבר שורה בסוף הקובץ")
    for n, line in enumerate(data.decode("utf-8-sig").split("\n"), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            err(f"queries.jsonl:{n}: JSON לא תקין ({e})"); continue
        if not isinstance(r, dict):
            err(f"queries.jsonl:{n}: השורה אינה אובייקט"); continue
        if list(r.keys()) != FIELDS:
            missing = [k for k in FIELDS if k not in r]
            extra = [k for k in r if k not in FIELDS]
            if missing or extra:
                err(f"queries.jsonl:{n}: שדות חסרים {missing}, שדות מיותרים {extra}")
            else:
                err(f"queries.jsonl:{n}: סדר השדות שונה מהסכמה")
            continue
        r["_n"] = n
        rows.append(r)
    if not rows:
        err("queries.jsonl ריק")

    seen = set()
    for r in rows:
        w = f"queries.jsonl:{r['_n']} ({r['id']})"
        for k in FIELDS:
            if not isinstance(r[k], str):
                err(f"{w}: השדה {k} חייב להיות מחרוזת")
            elif not r[k].strip() and k not in OPTIONAL_EMPTY:
                err(f"{w}: השדה {k} ריק")
        if any(not isinstance(r[k], str) for k in FIELDS):
            continue
        if not re.fullmatch(re.escape(prefix) + r"-\d{3,}", r["id"]):
            err(f"{w}: ה-id חייב להתאים ל-{prefix}-NNN")
        if r["id"] in seen:
            err(f"{w}: id כפול")
        seen.add(r["id"])
        if r["type"] not in TYPES: err(f"{w}: type לא חוקי ({r['type']})")
        if r["split"] not in SPLITS: err(f"{w}: split לא חוקי ({r['split']})")
        if r["near_miss_same_amud"] not in YESNO: err(f"{w}: near_miss_same_amud חייב להיות כן/לא")
        if r["correct_quote"] == r["near_miss_quote"]:
            err(f"{w}: הציטוט הנכון והכמעט נכון זהים")
        for which in ("correct", "near_miss"):
            ref, line_s, quote = r[f"{which}_ref"], r[f"{which}_line"], r[f"{which}_quote"]
            pr = parse_ref(ref, masechet)
            if not pr:
                err(f"{w}: {which}_ref לא תקין ({ref})"); continue
            if pr not in ranges:
                err(f"{w}: {which}_ref מצביע על עמוד שאינו בקובץ המקור ({ref})"); continue
            if not LINE_RE.match(line_s):
                err(f"{w}: {which}_line לא תקין ({line_s})"); continue
            a, b = span(line_s)
            if a < 1 or b > len(lines) or a > b:
                err(f"{w}: {which}_line מחוץ לקובץ ({line_s})"); continue
            lo, hi = ranges[pr]
            if a < lo or b > hi:
                err(f"{w}: {which}_line {line_s} אינו בתוך {ref} (שורות {lo}-{hi})")
            seg = lines[a - 1:b]
            q = library.norm(quote)
            if q not in "\n".join(seg) and q not in " ".join(seg):
                err(f"{w}: הציטוט של {which} לא נמצא בשורה {line_s}")
        same = r["correct_ref"] == r["near_miss_ref"]
        if r["near_miss_same_amud"] in YESNO and (r["near_miss_same_amud"] == "כן") != same:
            err(f"{w}: near_miss_same_amud לא עקבי עם ה-refs")

    # --- CSV ---
    with open(os.path.join(d, "queries.csv"), encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        try:
            header = next(rd)
        except StopIteration:
            err("queries.csv ריק"); return errs
        if header != FIELDS:
            err(f"queries.csv: הכותרת שונה מהסכמה. חסרות {[c for c in FIELDS if c not in header]}, מיותרות {[c for c in header if c not in FIELDS]}")
        csv_rows = []
        for i, cells in enumerate(rd, 2):
            if not any(c.strip() for c in cells):
                continue
            if len(cells) != len(FIELDS):
                err(f"queries.csv:{i}: {len(cells)} עמודות במקום {len(FIELDS)}"); continue
            csv_rows.append(dict(zip(FIELDS, cells)))
    if header == FIELDS:
        by_id = {r["id"]: {k: r[k] for k in FIELDS} for r in rows if "id" in r}
        csv_ids = [r["id"] for r in csv_rows]
        if len(csv_ids) != len(set(csv_ids)):
            err("queries.csv: id כפולים")
        for cid in csv_ids:
            if cid not in by_id: err(f"queries.csv: ה-id {cid} לא קיים ב-JSONL")
        for jid in by_id:
            if jid not in csv_ids: err(f"queries.csv: ה-id {jid} חסר (קיים ב-JSONL)")
        for r in csv_rows:
            j = by_id.get(r["id"])
            if j and r != j:
                diff = [k for k in FIELDS if r[k] != j[k]]
                err(f"queries.csv: {r['id']} שונה מה-JSONL בשדות {diff}")
    return errs


def main(argv):
    offline = "--offline" in argv
    args = [a for a in argv[1:] if a != "--offline"]
    targets = args or sorted(
        os.path.join("datasets", n) for n in os.listdir("datasets")
        if os.path.isdir(os.path.join("datasets", n)))
    all_errs, total = [], 0
    for t in targets:
        e = validate_dataset(t, offline=offline)
        if os.path.isfile(os.path.join(t, "queries.jsonl")):
            with open(os.path.join(t, "queries.jsonl"), encoding="utf-8") as f:
                total += sum(1 for l in f if l.strip())
        print(f"{'✗' if e else '✓'} {t}  ({len(e)} בעיות)")
        all_errs += e
    for e in all_errs[:60]:
        print(" -", e)
    if len(all_errs) > 60:
        print(f" ... ועוד {len(all_errs) - 60}")
    print(f"נבדקו {len(targets)} מערכים, {total} שאילתות")
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
