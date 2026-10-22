"""גישה לקובצי ספרים ב-Otzaria, עם pin לקומיט ול-hash ולנירמול אחיד."""
import hashlib, os, re, urllib.parse, urllib.request
from pathlib import PurePosixPath

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE_DIR = os.path.join(ROOT, ".cache", "library")
NIK = re.compile(r"[\\u0591-\\u05C7]")
TAG = re.compile(r"<[^>]+>")
CANONICAL_REPO = "Otzaria/otzaria-library"
CANONICAL_REPO_URL = "https://github.com/Otzaria/otzaria-library"
SOURCE_META_KEYS = {
    "book_name", "source_category", "id_prefix", "origin_repo", "origin_path",
    "origin_commit", "origin_sha256", "note",
}


def norm(s):
    """הסרת תגיות וניקוד, ואחידות בגרשיים ובשם השם המפורש."""
    s = NIK.sub("", TAG.sub("", s))
    s = s.replace("״", '"').replace("׳", "'").replace("יהוה", "ה'")
    return re.sub(r"\\s+", " ", s).strip()


def repo_slug(value):
    """Normalize an Otzaria GitHub URL or owner/repository string."""
    value = str(value or "").strip()
    if "://" not in value:
        value = "https://github.com/" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        return ""
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return ""
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def source_category_from_path(origin_path):
    """Return the top-level category under a committed ספרים/אוצריא directory."""
    if not isinstance(origin_path, str) or not origin_path:
        raise ValueError("origin_path must be a non-empty repository-relative path")
    if "\\\\" in origin_path or origin_path.startswith("/"):
        raise ValueError("origin_path must use a relative POSIX path")
    path = PurePosixPath(origin_path)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("origin_path must not contain empty, '.' or '..' path parts")
    if path.suffix.lower() != ".txt":
        raise ValueError("origin_path must point to an Otzaria .txt book")
    matches = [
        i for i in range(len(path.parts) - 1)
        if path.parts[i] == "ספרים" and path.parts[i + 1] == "אוצריא"
    ]
    if len(matches) != 1:
        raise ValueError("origin_path must be inside a committed ספרים/אוצריא/ book directory")
    category_index = matches[0] + 2
    if category_index >= len(path.parts) - 1:
        raise ValueError("origin_path must include a category and a book filename after ספרים/אוצריא/")
    category = path.parts[category_index].strip()
    if not category:
        raise ValueError("could not determine source category from origin_path")
    return category


def validate_source_origin(meta):
    """Fail unless provenance points to a .txt book in the Otzaria library repository."""
    slug = repo_slug(meta.get("origin_repo"))
    if slug != CANONICAL_REPO:
        raise ValueError(
            f"origin_repo must be {CANONICAL_REPO_URL}; got {meta.get('origin_repo')!r}"
        )
    category = source_category_from_path(meta.get("origin_path"))
    if meta.get("source_category") != category:
        raise ValueError(
            f"source_category {meta.get('source_category')!r} does not match "
            f"the library path category {category!r}"
        )
    expected_book_name = PurePosixPath(meta["origin_path"]).stem
    if meta.get("book_name") != expected_book_name:
        raise ValueError(
            f"book_name must match the Otzaria library filename stem {expected_book_name!r}"
        )
    return category


def raw_url(meta, ref):
    repo = repo_slug(meta["origin_repo"])
    encoded_path = urllib.parse.quote(meta["origin_path"], safe="/")
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{encoded_path}"


def fetch(meta, ref):
    with urllib.request.urlopen(raw_url(meta, ref), timeout=120) as response:
        return response.read()


def cache_path(slug, meta):
    identity = hashlib.sha256(
        (repo_slug(meta["origin_repo"]) + "\\0" + meta["origin_path"]).encode("utf-8")
    ).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"source-{identity}-{meta['origin_commit'][:10]}.txt")


def get_pinned(slug, meta, offline=False):
    """מחזיר (bytes, שגיאה); המקור חייב להתאים לקומיט ול-SHA-256 הנעוצים."""
    try:
        validate_source_origin(meta)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"source provenance is invalid: {exc}"

    want = meta["origin_sha256"]
    cp = cache_path(slug, meta)
    if os.path.isfile(cp):
        with open(cp, "rb") as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() == want:
            return data, None
    if offline:
        return None, "אין עותק תקין במטמון והבדיקה רצה ב-offline. להריץ פעם אחת עם חיבור לרשת"
    try:
        data = fetch(meta, meta["origin_commit"])
    except Exception as exc:
        return None, f"לא ניתן למשוך את קובץ המקור ({type(exc).__name__}: {exc})"
    if hashlib.sha256(data).hexdigest() != want:
        return None, "קובץ המקור שונה מ-origin_sha256 שבקובץ המטא־נתונים"
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cp, "wb") as handle:
        handle.write(data)
    return data, None
