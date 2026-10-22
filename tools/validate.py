#!/usr/bin/env python3
"""בדיקות תקינות לכל מערכי השאילתות ב-datasets/.

שם התיקייה הוא שם המסכת בעברית (למשל datasets/תענית). כל תיקיית מערך חייבת להכיל:
    <מסכת>.jsonl        המקור לעבודה
    <מסכת>.csv          אותם נתונים לפתיחה באקסל (נגזר מה-JSONL, חייב להיות זהה לו)
    <מסכת>.מקור.json    שם המסכת, קידומת id, ומקור הטקסט: קומיט קבוע, נתיב ו-sha256 של הקובץ בספריית אוצריא

הטקסט עצמו לא נשמר במאגר. הבודק מושך אותו מהקומיט הקבוע (או משתמש במטמון ב-.cache/) ובודק מולו.

שימוש:
    python tools/validate.py                  # בודק את כל המערכים
    python tools/validate.py datasets/תענית  # בודק מערך אחד
    python tools/validate.py --offline        # רק מהמטמון, בלי רשת
קוד יציאה 1 אם נמצאה בעיה.
"""
import csv, hashlib, json, os, re, sys
from pathlib import Path

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)
import library
import source_refs

FIELDS = ["id", "query", "type", "correct_ref", "correct_quote", "correct_line",
          "near_miss_ref", "near_miss_quote", "near_miss_line",
          "near_miss_same_section", "split", "verified_by_human"]
OPTIONAL_EMPTY = {"verified_by_human"}
TYPES = {"conceptual", "short"}
SPLITS = {"test", "train"}
YESNO = {"כן", "לא"}
META_KEYS = library.SOURCE_META_KEYS
LINE_RE = re.compile(r"^\d+(-\d+)?$")


def span(s):
    a, _, b = s.partition("-")
    return int(a), int(b or a)


def validate_dataset(d, loader=None, offline=False, require_verified=None):
    """Validate a dataset against a pinned .txt book from Otzaria's library.

    loader(d, meta) -> (bytes, error) lets unit tests replace network fetching.
    """
    errs = []
    def err(msg): errs.append(f"{d}: {msg}")

    dataset_path = Path(d).absolute()
    symlink = path_symlink_component(dataset_path)
    if symlink is not None:
        return [f"{symlink}: נתיב המכיל קישור סמלי אינו נבדק"]
    if dataset_path.is_dir():
        links = symlink_entries(dataset_path)
        if links:
            return [f"{link}: קישורים סמליים אסורים בתוך מערך נתונים" for link in links]

    name = os.path.basename(os.path.normpath(d))
    f_jsonl, f_csv, f_meta = f"{name}.jsonl", f"{name}.csv", f"{name}.מקור.json"
    for n in (f_jsonl, f_csv, f_meta):
        if not os.path.isfile(os.path.join(d, n)):
            err(f"חסר הקובץ {n}")
    if errs:
        return errs

    # --- קובץ המקור (<מסכת>.מקור.json) ---
    try:
        with open(os.path.join(d, f_meta), encoding="utf-8") as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return [f"{d}/{f_meta}: JSON לא תקין ({e})"]
    except (UnicodeDecodeError, OSError) as e:
        return [f"{d}/{f_meta}: לא ניתן לקרוא JSON תקין ({e})"]
    if not isinstance(meta, dict):
        return [f"{d}/{f_meta}: המטא־נתונים חייבים להיות אובייקט JSON"]
    if set(meta) != META_KEYS:
        err(f"{f_meta}: מפתחות לא תקינים. חסרים {sorted(META_KEYS - set(meta))}, מיותרים {sorted(set(meta) - META_KEYS)}")
        return errs
    try:
        source_category = library.validate_source_origin(meta)
    except (KeyError, TypeError, ValueError) as exc:
        err(f"{f_meta}: מקור לא תקין: {exc}")
        return errs
    if not all(isinstance(meta.get(key), str) for key in META_KEYS):
        err(f"{f_meta}: כל ערכי המטא־נתונים חייבים להיות מחרוזות")
        return errs
    if not re.fullmatch(r"[a-z]+", meta["id_prefix"]):
        err(f"{f_meta}: id_prefix חייב להכיל אותיות לטיניות קטנות בלבד")
        return errs
    if not meta["book_name"].strip():
        err(f"{f_meta}: book_name אינו יכול להיות ריק")
        return errs
    if not (isinstance(meta.get("origin_commit"), str) and re.fullmatch(r"[0-9a-f]{40}", meta["origin_commit"])):
        err(f"{f_meta}: origin_commit חייב להיות SHA מלא של קומיט (40 תווים)")
        return errs
    if not (isinstance(meta.get("origin_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", meta["origin_sha256"])):
        err(f"{f_meta}: origin_sha256 חייב להיות SHA-256 מלא (64 תווים)")
        return errs

    repo_root = Path(TOOLS_DIR).parent
    if require_verified is None:
        require_verified = False
        try:
            relative = Path(d).resolve().relative_to(repo_root.resolve())
            require_verified = bool(relative.parts and relative.parts[0] == "datasets")
        except ValueError:
            pass

    # Approved/pending paths use datasets/<category>/<book> or drafts/<category>/<book>.
    try:
        relative = Path(d).resolve().relative_to(repo_root.resolve())
        if relative.parts and relative.parts[0] in {"datasets", "drafts"}:
            if len(relative.parts) != 3:
                err(f"נתיב מערך חייב להיות {relative.parts[0]}/<קטגוריה>/<שם ספר>")
            elif relative.parts[1] != source_category:
                err(f"קטגוריית התיקייה ({relative.parts[1]}) אינה תואמת לקטגוריית המקור ({source_category})")
    except ValueError:
        pass

    if meta.get("book_name") != name:
        err(f"שם התיקייה ({name}) חייב להיות זהה ל-book_name ב-{f_meta} ({meta.get('book_name')})")
        return errs
    if loader is None:
        data, why = library.get_pinned(name, meta, offline)
    else:
        data, why = loader(d, meta)
    if why:
        err(f"קובץ המקור מאוצריא: {why}")
        return errs
    if not isinstance(data, bytes):
        err("קובץ המקור חייב להיטען כ-bytes")
        return errs
    if hashlib.sha256(data).hexdigest() != meta["origin_sha256"]:
        err(f"קובץ המקור שונה מ-origin_sha256 שב-{f_meta}")
        return errs
    try:
        raw_lines = [line.rstrip("\r") for line in data.decode("utf-8").split("\n")]
        lines = [library.norm(line) for line in raw_lines]
        refs, section_ids = source_refs.line_reference_data(raw_lines)
    except (UnicodeDecodeError, ValueError) as exc:
        err(f"קובץ המקור או הכותרות אינם תקינים: {exc}")
        return errs
    prefix = meta["id_prefix"]

    # --- JSONL ---
    rows = []
    with open(os.path.join(d, f_jsonl), "rb") as f:
        data = f.read()
    if data.startswith(b"\xef\xbb\xbf"):
        err(f"{f_jsonl}: אסור BOM")
    if data and not data.endswith(b"\n"):
        err(f"{f_jsonl}: חסר מעבר שורה בסוף הקובץ")
    try:
        jsonl_text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        err(f"{f_jsonl}: הקובץ אינו בקידוד UTF-8 ({exc})")
        return errs
    for n, line in enumerate(jsonl_text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            err(f"{f_jsonl}:{n}: JSON לא תקין ({e})"); continue
        if not isinstance(r, dict):
            err(f"{f_jsonl}:{n}: השורה אינה אובייקט"); continue
        if list(r.keys()) != FIELDS:
            missing = [k for k in FIELDS if k not in r]
            extra = [k for k in r if k not in FIELDS]
            if missing or extra:
                err(f"{f_jsonl}:{n}: שדות חסרים {missing}, שדות מיותרים {extra}")
            else:
                err(f"{f_jsonl}:{n}: סדר השדות שונה מהסכמה")
            continue
        r["_n"] = n
        rows.append(r)
    if not rows:
        err(f"{f_jsonl} ריק")

    seen = set()
    for r in rows:
        w = f"{f_jsonl}:{r['_n']} ({r['id']})"
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
        if r["near_miss_same_section"] not in YESNO: err(f"{w}: near_miss_same_section חייב להיות כן/לא")
        if require_verified and not r["verified_by_human"].strip():
            err(f"{w}: מערך מאושר חייב לכלול verified_by_human")
        if r["correct_quote"] == r["near_miss_quote"]:
            err(f"{w}: הציטוט הנכון והכמעט נכון זהים")
        for which in ("correct", "near_miss"):
            ref, line_s, quote = r[f"{which}_ref"], r[f"{which}_line"], r[f"{which}_quote"]
            if not LINE_RE.match(line_s):
                err(f"{w}: {which}_line לא תקין ({line_s})"); continue
            a, b = span(line_s)
            if a < 1 or b > len(lines) or a > b:
                err(f"{w}: {which}_line מחוץ לקובץ ({line_s})"); continue
            expected_ref = refs[a - 1]
            if ref != expected_ref:
                err(f"{w}: {which}_ref אינו תואם למסלול הכותרות בשורה {a} ({ref!r} במקום {expected_ref!r})")
            expected_section = section_ids[a - 1]
            crossed = next(
                (
                    ln for ln in range(a + 1, b + 1)
                    if refs[ln - 1] != expected_ref or section_ids[ln - 1] != expected_section
                ),
                None,
            )
            if crossed is not None:
                err(f"{w}: {which}_line {line_s} חוצה גבול כותרת בשורה {crossed}")
            seg = lines[a - 1:b]
            q = library.norm(quote)
            if q not in "\n".join(seg) and q not in " ".join(seg):
                err(f"{w}: הציטוט של {which} לא נמצא בשורה {line_s}")
        if LINE_RE.match(r["correct_line"]) and LINE_RE.match(r["near_miss_line"]):
            ca, cb = span(r["correct_line"]); na, nb = span(r["near_miss_line"])
            if not (cb < na or nb < ca):
                err(f"{w}: הציטוט הנכון והכמעט נכון נמצאים באותה שורה "
                    f"({r['correct_line']} / {r['near_miss_line']}). שלילי חייב להיות משורה אחרת")
        same = r["correct_ref"] == r["near_miss_ref"]
        if r["near_miss_same_section"] in YESNO and (r["near_miss_same_section"] == "כן") != same:
            err(f"{w}: near_miss_same_section לא עקבי עם ה-refs")

    # --- CSV ---
    try:
        with open(os.path.join(d, f_csv), encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            try:
                header = next(rd)
            except StopIteration:
                err(f"{f_csv} ריק"); return errs
            if header != FIELDS:
                err(f"{f_csv}: הכותרת שונה מהסכמה. חסרות {[c for c in FIELDS if c not in header]}, מיותרות {[c for c in header if c not in FIELDS]}")
            csv_rows = []
            for i, cells in enumerate(rd, 2):
                if not any(c.strip() for c in cells):
                    continue
                if len(cells) != len(FIELDS):
                    err(f"{f_csv}:{i}: {len(cells)} עמודות במקום {len(FIELDS)}"); continue
                csv_rows.append(dict(zip(FIELDS, cells)))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        err(f"{f_csv}: לא ניתן לקרוא CSV תקין ({exc})")
        return errs
    if header == FIELDS:
        by_id = {r["id"]: {k: r[k] for k in FIELDS} for r in rows if "id" in r}
        csv_ids = [r["id"] for r in csv_rows]
        if len(csv_ids) != len(set(csv_ids)):
            err(f"{f_csv}: id כפולים")
        for cid in csv_ids:
            if cid not in by_id: err(f"{f_csv}: ה-id {cid} לא קיים ב-JSONL")
        for jid in by_id:
            if jid not in csv_ids: err(f"{f_csv}: ה-id {jid} חסר (קיים ב-JSONL)")
        for r in csv_rows:
            j = by_id.get(r["id"])
            if j and r != j:
                diff = [k for k in FIELDS if r[k] != j[k]]
                err(f"{f_csv}: {r['id']} שונה מה-JSONL בשדות {diff}")
    return errs


def symlink_entries(root):
    """List symbolic links without traversing them."""
    root = Path(root)
    if root.is_symlink():
        return [root]
    if not root.is_dir():
        return []
    found = []
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        for name in list(dirs):
            candidate = base / name
            if candidate.is_symlink():
                found.append(candidate)
                dirs.remove(name)
        for name in files:
            candidate = base / name
            if candidate.is_symlink():
                found.append(candidate)
    return sorted(found)


def dataset_dirs(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        return []
    # Walk without following symlinks. Catch canonical nested folders, metadata
    # files, and misplaced top-level folders containing JSONL.
    candidates = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = [name for name in dirs if not (base / name).is_symlink()]
        relative = base.relative_to(root)
        if any(name.endswith(".מקור.json") and not (base / name).is_symlink() for name in files):
            candidates.add(base)
        if len(relative.parts) == 2:
            candidates.add(base)
        if len(relative.parts) == 1 and any(name.endswith(".jsonl") for name in files):
            candidates.add(base)
    return sorted(candidates)


def path_symlink_component(path):
    path = Path(path).absolute()
    for component in reversed((path, *path.parents)):
        try:
            if component.is_symlink():
                return component
        except OSError:
            continue
    return None


def discover_target(path):
    path = Path(path)
    if path.is_file():
        path = path.parent
    if not path.exists():
        return []
    if (path / f"{path.name}.מקור.json").is_file():
        return [path]
    return dataset_dirs(path)


def main(argv):
    offline = "--offline" in argv
    args = [a for a in argv[1:] if a != "--offline"]
    repo_root = Path(TOOLS_DIR).parent.resolve()
    scan_errors = []
    if args:
        targets = []
        for arg in args:
            supplied = Path(arg)
            supplied = supplied if supplied.is_absolute() else Path.cwd() / supplied
            symlink = path_symlink_component(supplied)
            if symlink is not None:
                scan_errors.append(f"{symlink}: paths containing symlinks are not validated")
                continue
            found = discover_target(supplied)
            targets.extend((p, None) for p in found)
            if not found:
                targets.append((supplied, None))
    else:
        targets = []
        for root_name, required in (("datasets", True), ("drafts", False)):
            root = repo_root / root_name
            if root.is_symlink():
                scan_errors.append(f"{root}: dataset root must not be a symlink")
                continue
            if root.exists() and not root.is_dir():
                scan_errors.append(f"{root}: dataset root must be a directory")
                continue
            links = symlink_entries(root)
            scan_errors.extend(f"{link}: symlinks are not allowed under {root_name}" for link in links)
            candidates = dataset_dirs(root)
            targets.extend(
                (p, required) for p in candidates
                if not any(p == link or p in link.parents for link in links)
            )

    unique = {}
    for path, required in targets:
        key = str(path)
        if key not in unique:
            unique[key] = required
        elif required is True:
            unique[key] = True

    all_errs, total = list(scan_errors), 0
    for value, required in unique.items():
        target = Path(value)
        e = validate_dataset(str(target), offline=offline, require_verified=required)
        jp = target / f"{target.name}.jsonl"
        if jp.is_file() and not jp.is_symlink():
            try:
                with jp.open(encoding="utf-8") as handle:
                    total += sum(1 for line in handle if line.strip())
            except (OSError, UnicodeDecodeError) as exc:
                all_errs.append(f"{jp}: לא ניתן לספור שורות ({exc})")
        print(f"{'✗' if e else '✓'} {target}  ({len(e)} בעיות)")
        all_errs += e
    for error in all_errs[:60]:
        print(" -", error)
    if len(all_errs) > 60:
        print(f" ... ועוד {len(all_errs) - 60}")
    print(f"נבדקו {len(unique)} מערכים, {total} שאילתות")
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
