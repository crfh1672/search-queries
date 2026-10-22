"""גישה לקובצי ספרים ב-Otzaria, עם pin לקומיט ול-hash ולנירמול אחיד."""
import hashlib, os, re, stat, tempfile, urllib.parse, urllib.request
from pathlib import Path, PurePosixPath

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE_DIR = os.path.join(ROOT, ".cache", "library")
NIK = re.compile(r"[\u0591-\u05C7]")
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


def source_category_from_path(origin_path):
    """Return the top-level category under a committed ספרים/אוצריא directory."""
    if not isinstance(origin_path, str) or not origin_path:
        raise ValueError("origin_path must be a non-empty repository-relative path")
    if "\\" in origin_path or origin_path.startswith("/"):
        raise ValueError("origin_path must use a relative POSIX path")
    if any(part in {"", ".", ".."} for part in origin_path.split("/")):
        raise ValueError("origin_path must not contain empty, '.' or '..' path parts")
    path = PurePosixPath(origin_path)
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


def is_path_link(path):
    path = Path(path)
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


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
    except FileNotFoundError:
        return None
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
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            return None
        if hashlib.sha256(data).hexdigest() != expected_hash:
            return None
        return data
    except OSError:
        return None
    finally:
        os.close(fd)


def cache_path(slug, meta):
    identity = hashlib.sha256(
        (repo_slug(meta["origin_repo"]) + "\0" + meta["origin_path"]).encode("utf-8")
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
    elif offline:
        return None, f"לא ניתן להשתמש במטמון באופן בטוח: {cache_problem or 'תיקיית המטמון אינה זמינה'}"
    if offline:
        return None, "אין עותק תקין במטמון והבדיקה רצה ב-offline. להריץ פעם אחת עם חיבור לרשת"
    try:
        data = fetch(meta, meta["origin_commit"])
    except Exception as exc:
        return None, f"לא ניתן למשוך את קובץ המקור ({type(exc).__name__}: {exc})"
    if hashlib.sha256(data).hexdigest() != want:
        return None, "קובץ המקור שונה מ-origin_sha256 שבקובץ המטא־נתונים"

    # Cache is an optimization, never a reason to trust or overwrite a symlink.
    try:
        cache_dir = safe_cache_directory(create=True)
        cache_file = Path(cache_dir) / Path(cp).name
        fd, temporary = tempfile.mkstemp(prefix=".source-", suffix=".tmp", dir=cache_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, cache_file)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    except (OSError, ValueError):
        # The fetched bytes have already been hash-verified; a blocked cache
        # write should not invalidate a successful source read.
        pass
    return data, None
