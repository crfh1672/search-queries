"""גישה לקובצי ספרים ב-Otzaria, עם pin לקומיט ול-hash ולנירמול אחיד."""
import hashlib, json, os, re, stat, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path, PurePosixPath

import pathsafe
from pathsafe import is_link as is_path_link  # noqa: F401  (kept for older callers)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE_DIR = os.path.join(ROOT, ".cache", "library")
NIK = re.compile(r"[֑-ׇ]")
TAG = re.compile(r"<[^>]+>")
CANONICAL_REPO = "Otzaria/otzaria-library"
CANONICAL_REPO_URL = "https://github.com/Otzaria/otzaria-library"
SOURCE_META_KEYS = {
    "book_name", "source_category", "id_prefix", "origin_repo", "origin_path",
    "origin_commit", "origin_sha256", "note",
}

# The source roots that Otzaria's release build merges into the library the
# application ships (BOOK_ROOTS in otzaria-library/manual_links_packaging.py;
# keep in the same order). Every root contributes <root>/ספרים/אוצריא/…, and a
# LATER root overrides an EARLIER one for the same relative path.
#
# NOT packaged, therefore never valid sources here: extraBooks/, docxToOtzaria/,
# DictaToOtzaria/לא ערוך/, MoreBooks/ספרים/ outside אוצריא/, and any
# <source>/ספרים/<something other than אוצריא>/ such as ספרים/לא ממויין/.
PACKAGED_ROOTS = (
    "Ben-YehudaToOtzaria",
    "DictaToOtzaria/ערוך",
    "OnYourWayToOtzaria",
    "OraytaToOtzaria",
    "tashmaToOtzaria",
    "sefariaToOtzaria/sefaria_export",
    "sefariaToOtzaria/sefaria_api",
    "MoreBooks",
    "KSK",
    "wikiJewishBooksToOtzaria",
    "wikisourceToOtzaria",
    "ToratEmetToOtzaria",
    "pninimToOtzaria",
    "National-LibraryToOtzaria",
    "yam-HaHachmaToOtzaria",
    "BeitAharonVeYisraelToOtzaria",
)
LIBRARY_DIR = ("ספרים", "אוצריא")


def norm(s):
    """הסרת תגיות וניקוד, ואחידות בגרשיים ובשם השם המפורש."""
    s = NIK.sub("", TAG.sub("", s))
    s = s.replace("״", '"').replace("׳", "'").replace("יהוה", "ה'")
    return re.sub(r"\s+", " ", s).strip()


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


def schema_origin_path_pattern():
    """The regex that schema/source.schema.json must carry for origin_path."""
    # '-' must stay unescaped: ECMA-262 with the 'u' flag rejects '\-' outside a class.
    roots = "|".join(re.sub(r"([.^$*+?{}\[\]\\|()])", r"\\\1", root) for root in PACKAGED_ROOTS)
    return (
        r"^(?!.*\\)(?!.*//)(?!.*(?:^|/)\.{1,2}(?:/|$))"
        r"(?!.*(?:^|/)ספרים/אוצריא/(?:.*/)?ספרים/אוצריא/)"
        rf"(?:{roots})/ספרים/אוצריא/[^/]+/(?:[^/]+/)*[^/]+\.txt$"
    )


def split_packaged_path(origin_path):
    """Return (root_index, parts_below_library_dir) for a packaged book path."""
    if not isinstance(origin_path, str) or not origin_path:
        raise ValueError("origin_path must be a non-empty repository-relative path")
    if "\\" in origin_path or origin_path.startswith("/"):
        raise ValueError("origin_path must use a relative POSIX path")
    if any(part in {"", ".", ".."} for part in origin_path.split("/")):
        raise ValueError("origin_path must not contain empty, '.' or '..' path parts")
    path = PurePosixPath(origin_path)
    if path.suffix != ".txt":
        raise ValueError("origin_path must point to an Otzaria .txt book")
    for index, root in enumerate(PACKAGED_ROOTS):
        prefix = tuple(root.split("/")) + LIBRARY_DIR
        if path.parts[: len(prefix)] == prefix:
            below = path.parts[len(prefix):]
            break
    else:
        raise ValueError(
            "origin_path must be <packaged source root>/ספרים/אוצריא/<category>/…; "
            "extraBooks/, DictaToOtzaria/לא ערוך/ and ספרים/<not אוצריא>/ are not "
            f"part of the shipped library (packaged roots: {', '.join(PACKAGED_ROOTS)})"
        )
    if len(below) < 2:
        raise ValueError("origin_path must include a category and a book filename after ספרים/אוצריא/")
    if any(below[i:i + 2] == LIBRARY_DIR for i in range(len(below) - 1)):
        raise ValueError("origin_path must not repeat ספרים/אוצריא/")
    return index, below


def source_category_from_path(origin_path):
    """Return the top-level category under a packaged ספרים/אוצריא directory."""
    _, below = split_packaged_path(origin_path)
    category = below[0].strip()
    if not category:
        raise ValueError("could not determine source category from origin_path")
    return category


def validate_source_origin(meta):
    """Fail unless provenance points to a packaged .txt book in the Otzaria library repository."""
    if meta.get("origin_repo") != CANONICAL_REPO_URL:
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
    if not isinstance(meta.get("origin_commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", meta["origin_commit"]):
        raise ValueError("origin_commit חייב להיות SHA מלא (40 תווים)")
    if not isinstance(meta.get("origin_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", meta["origin_sha256"]):
        raise ValueError("origin_sha256 must be a full 64-character SHA-256")
    return category


def raw_url(meta, ref):
    repo = repo_slug(meta["origin_repo"])
    encoded_path = urllib.parse.quote(meta["origin_path"], safe="/")
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{encoded_path}"


def fetch(meta, ref):
    with urllib.request.urlopen(raw_url(meta, ref), timeout=120) as response:
        return response.read()


def safe_cache_directory(create=False):
    """Return the cache directory only if every existing component stays in this repo."""
    root = Path(ROOT).resolve(strict=True)
    cache_root = root / ".cache"
    cache_dir = cache_root / "library"
    for directory in (cache_root, cache_dir):
        if is_path_link(directory):
            raise ValueError(f"cache directory must not be a symlink or junction: {directory}")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"cache path is not a directory: {directory}")
        if create and not directory.exists():
            directory.mkdir()
        if directory.exists():
            try:
                directory.resolve(strict=True).relative_to(root)
            except (OSError, ValueError) as exc:
                raise ValueError(f"cache directory resolves outside repository: {directory}") from exc
    return cache_dir if cache_dir.is_dir() else None


def read_cache_file(path, expected_hash):
    """Read only a regular cache file, refusing symlink/junction redirection."""
    if is_path_link(path):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        if hashlib.sha256(data).hexdigest() != expected_hash:
            return None
        return data
    except OSError:
        return None
    finally:
        os.close(fd)


def _cache_identity(meta):
    return hashlib.sha256(
        (repo_slug(meta["origin_repo"]) + "\0" + meta["origin_path"]).encode("utf-8")
    ).hexdigest()[:16]


def cache_path(slug, meta):
    return os.path.join(CACHE_DIR, f"source-{_cache_identity(meta)}-{meta['origin_commit'][:10]}.txt")


def _write_cache_atomic(name, data):
    """Best-effort atomic cache write; a failure never invalidates a verified read."""
    try:
        cache_dir = safe_cache_directory(create=True)
        fd, temporary = tempfile.mkstemp(prefix=".cache-", suffix=".tmp", dir=cache_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, Path(cache_dir) / name)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    except (OSError, ValueError):
        pass


def get_pinned(slug, meta, offline=False):
    """מחזיר (bytes, שגיאה); המקור חייב להתאים לקומיט ול-SHA-256 הנעוצים."""
    try:
        validate_source_origin(meta)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"source provenance is invalid: {exc}"

    want = meta["origin_sha256"]
    cp = cache_path(slug, meta)
    try:
        cache_dir = safe_cache_directory(create=False)
    except (OSError, ValueError) as exc:
        cache_dir = None
        cache_problem = str(exc)
    else:
        cache_problem = None
    if cache_dir is not None:
        cached = read_cache_file(Path(cache_dir) / Path(cp).name, want)
        if cached is not None:
            return cached, None
    elif offline and cache_problem:
        return None, f"לא ניתן להשתמש במטמון באופן בטוח: {cache_problem}"
    if offline:
        return None, "אין עותק תקין במטמון והבדיקה רצה ב-offline. להריץ פעם אחת עם חיבור לרשת"
    try:
        data = fetch(meta, meta["origin_commit"])
    except Exception as exc:
        return None, f"לא ניתן למשוך את קובץ המקור ({type(exc).__name__}: {exc})"
    if hashlib.sha256(data).hexdigest() != want:
        return None, "קובץ המקור שונה מ-origin_sha256 שבקובץ המטא־נתונים"
    _write_cache_atomic(Path(cp).name, data)
    return data, None


# --- shadowing -------------------------------------------------------------

_RETRY_STATUS = {429, 500, 502, 503, 504}
_ATTEMPTS = 4
_REQUEST_TIMEOUT = 20
_SCAN_BUDGET = 180  # seconds for the whole shadow scan, shared by all roots


def _sleep(seconds):
    time.sleep(seconds)


def _now():
    return time.monotonic()


def _exists_at(url, opener, deadline=None):
    """HEAD request with a few bounded retries for rate limits and server errors.

    404 means "not there". Any other persistent failure propagates, so an
    unreachable answer is never mistaken for "not shadowed". *deadline* is a
    monotonic time after which no further attempt is started.
    """
    request = urllib.request.Request(url, method="HEAD")
    for attempt in range(_ATTEMPTS):
        if deadline is not None and _now() >= deadline:
            raise TimeoutError("the shadow check exceeded its time budget")
        try:
            with opener(request, timeout=_REQUEST_TIMEOUT):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            if exc.code not in _RETRY_STATUS or attempt == _ATTEMPTS - 1:
                raise
        except urllib.error.URLError:
            if attempt == _ATTEMPTS - 1:
                raise
        _sleep(2 ** attempt)


def shadow_cache_name(meta):
    """Cache file name; it changes with the full commit and with the root list."""
    roots = hashlib.sha256("\n".join(PACKAGED_ROOTS).encode("utf-8")).hexdigest()[:12]
    return f"shadow-{_cache_identity(meta)}-{meta['origin_commit']}-{roots}.json"


def shadowing_roots(meta, offline=False, opener=None):
    """Later packaged roots that hold the same relative path at the pinned commit.

    A non-empty result means the release build overwrites the pinned file with
    another copy, so the text a user sees is not the text the dataset cites.
    Returns None when the answer is unknown (offline without a cached answer).
    Results are cached because a commit is immutable.
    """
    index, below = split_packaged_path(meta["origin_path"])
    name = shadow_cache_name(meta)
    try:
        cache_dir = safe_cache_directory(create=False)
    except (OSError, ValueError):
        cache_dir = None
    if cache_dir is not None:
        cached = Path(cache_dir) / name
        if not is_path_link(cached) and cached.is_file():
            try:
                roots = json.loads(cached.read_text(encoding="utf-8"))
                if isinstance(roots, list) and all(isinstance(r, str) for r in roots):
                    return roots
            except (OSError, ValueError):
                pass
    if offline:
        return None
    opener = opener or urllib.request.urlopen
    shadows = []
    deadline = _now() + _SCAN_BUDGET
    for later in PACKAGED_ROOTS[index + 1:]:
        candidate = dict(meta, origin_path="/".join((later, *LIBRARY_DIR, *below)))
        if _exists_at(raw_url(candidate, meta["origin_commit"]), opener, deadline):
            shadows.append(later)
    _write_cache_atomic(name, json.dumps(shadows).encode("utf-8"))
    return shadows
