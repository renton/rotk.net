"""Best-effort favicon scraper.

Given a URL, parses the host, fetches `https://<host>/favicon.ico`, and
saves it to `app/static/favicons/<host>_favicon.ico` so Url.favicon can
point at the local copy. Filenames are keyed by host so the same site
referenced from many Url rows uses one shared local file.

Failure modes (timeout, 404, non-image response, body too large) are
silent — fetch_favicon returns None and the caller stores no favicon
path. Admin can always set one manually on the Url edit form.

Why a host-keyed local copy rather than hot-linking:
  - Survives the source site going away.
  - One CSP host-allowlist exception (`'self'`) covers every link.
  - Lets us inline `<img src="{{ url_for('static', ...) }}">` instead of
    going through an `<img referrerpolicy="...">` proxy.
"""
import os
import re
import urllib.parse

import requests


FAVICON_DIR = "favicons"   # under app/static/
USER_AGENT = (
    "rotk.net/1.0 (+https://rotk.net; "
    "an annotated Romance of the Three Kingdoms edition)"
)
TIMEOUT_SECONDS = 10
MAX_BYTES = 1 * 1024 * 1024   # 1 MB — way more than any real favicon


_HOSTNAME_SAFE_RE = re.compile(r'[^A-Za-z0-9._-]+')


def _sanitise_host(host):
    """Reduce a hostname to a filesystem-safe form. Strips userinfo,
    ports, and anything outside [A-Za-z0-9._-]."""
    if not host:
        return ""
    host = host.split('@', 1)[-1]      # strip userinfo if any
    host = host.split(':', 1)[0]       # strip port
    host = host.strip().lower()
    return _HOSTNAME_SAFE_RE.sub('_', host)


def _looks_like_image(content_type, header_bytes):
    """Sniff the response: prefer the declared Content-Type, fall back
    to a magic-byte check that matches our portrait extension probe."""
    ct = (content_type or '').lower().split(';', 1)[0].strip()
    if ct.startswith('image/'):
        return True
    # Some hosts return application/octet-stream or no type for .ico — fall
    # back to magic-byte detection.
    if header_bytes.startswith(b'\x00\x00\x01\x00'):     # ICO
        return True
    if header_bytes.startswith(b'\x89PNG\r\n\x1a\n'):    # PNG
        return True
    if header_bytes.startswith(b'\xff\xd8\xff'):         # JPEG
        return True
    if header_bytes[:6] in (b'GIF87a', b'GIF89a'):       # GIF
        return True
    if header_bytes[:4] == b'RIFF' and header_bytes[8:12] == b'WEBP':
        return True
    if header_bytes.lstrip().startswith(b'<svg') or b'<svg' in header_bytes[:512]:
        return True
    return False


def fetch_favicon(target_url, static_folder):
    """Download the favicon for target_url and save it under
    `<static_folder>/<FAVICON_DIR>/<host>_favicon.ico`. Returns the
    static-relative path (e.g. "favicons/wikipedia.org_favicon.ico") or
    None if anything went wrong.

    `static_folder` is normally `current_app.static_folder` — passed in
    so this module stays import-safe outside a Flask app context."""
    if not target_url:
        return None

    try:
        parsed = urllib.parse.urlparse(target_url)
    except Exception:
        return None
    host = _sanitise_host(parsed.netloc)
    if not host:
        return None

    favicons_dir = os.path.join(static_folder, FAVICON_DIR)
    os.makedirs(favicons_dir, exist_ok=True)

    filename = f"{host}_favicon.ico"
    local_path = os.path.join(favicons_dir, filename)
    static_rel = f"{FAVICON_DIR}/{filename}"

    # Dedupe: if we already have a non-empty file for this host, reuse.
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return static_rel

    scheme = parsed.scheme or 'https'
    candidate = f"{scheme}://{parsed.netloc}/favicon.ico"

    try:
        resp = requests.get(
            candidate,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    # Read up to MAX_BYTES (defensive) and decide if it's an image.
    chunks = []
    total = 0
    for chunk in resp.iter_content(8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_BYTES:
            return None
        chunks.append(chunk)
    body = b''.join(chunks)
    if total < 16:
        return None
    if not _looks_like_image(resp.headers.get('Content-Type'), body[:32]):
        return None

    with open(local_path, 'wb') as f:
        f.write(body)

    return static_rel
