"""גישה לקובץ המסכת בספריית אוצריא: משיכה מקומיט קבוע, מטמון מקומי ונירמול."""
import hashlib, os, re, urllib.parse, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE_DIR = os.path.join(ROOT, ".cache", "library")
NIK = re.compile(r"[\u0591-\u05C7]")
TAG = re.compile(r"<[^>]+>")


def norm(s):
    """הסרת תגיות וניקוד, ואחידות בגרשיים ובשם השם המפורש."""
    s = NIK.sub("", TAG.sub("", s))
    s = s.replace("״", '"').replace("׳", "'").replace("יהוה", "ה'")
    return re.sub(r"\s+", " ", s).strip()


def raw_url(meta, ref):
    repo = meta["origin_repo"].replace("https://github.com/", "")
    return f"https://raw.githubusercontent.com/{repo}/{ref}/" + urllib.parse.quote(meta["origin_path"])


def fetch(meta, ref):
    with urllib.request.urlopen(raw_url(meta, ref), timeout=120) as r:
        return r.read()


def cache_path(slug, meta):
    return os.path.join(CACHE_DIR, f"{slug}-{meta['origin_commit'][:10]}.txt")


def get_pinned(slug, meta, offline=False):
    """מחזיר (bytes, שגיאה). משתמש במטמון אם הוא תקין, אחרת מושך מהקומיט הקבוע."""
    want = meta["origin_sha256"]
    cp = cache_path(slug, meta)
    if os.path.isfile(cp):
        with open(cp, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() == want:
            return data, None
    if offline:
        return None, "אין עותק תקין במטמון והבדיקה רצה ב-offline. להריץ פעם אחת עם חיבור לרשת"
    try:
        data = fetch(meta, meta["origin_commit"])
    except Exception as e:  # noqa: BLE001
        return None, f"לא ניתן למשוך את קובץ הספרייה ({type(e).__name__}: {e})"
    if hashlib.sha256(data).hexdigest() != want:
        return None, "הקובץ שנמשך מהספרייה שונה מ-origin_sha256 שבקובץ <מסכת>.מקור.json"
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cp, "wb") as f:
        f.write(data)
    return data, None
