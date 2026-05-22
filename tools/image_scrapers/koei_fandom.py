"""Scrape character portraits from koei.fandom.com via the MediaWiki API.

Returns every File on the character's wiki page that looks like a portrait
of *that* character (filename starts with the character's name), with the
game-variant code parsed out of the filename's last parenthesised group
(e.g. "Cao Cao (DW9).png" -> variant_tag="DW9").

Why the API and not the rendered HTML:
- Fandom's Fastly layer 403s bot-flavoured UAs on the article pages.
- api.php is meant for programmatic use and stays open.

API flow:
1.  prop=images&titles=<Page>          — enumerate every File on the page
2.  prop=imageinfo&iiprop=url&titles=  — resolve each File to a CDN URL
    (batched up to 50 titles per call)
"""
import re

import requests

from . import ScrapedImage


SITE_NAME = "Koei Wiki (Fandom)"
API_URL = "https://koei.fandom.com/api.php"
WIKI_URL = "https://koei.fandom.com/wiki/"
USER_AGENT = (
    "rotk.net/1.0 (+https://rotk.net; "
    "an annotated Romance of the Three Kingdoms edition)"
)
REQUEST_HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT_SECONDS = 15
IMAGES_BATCH_SIZE = 50   # MediaWiki cap for `titles=A|B|...` per call.


# Trailing parenthesised group before the extension:
#   "Cao Cao (DW9).png"               -> "DW9"
#   "Cao Cao - Dark (DWU).png"        -> "DWU"
#   "Cao Cao 15th ... (DWEKD).jpg"    -> "DWEKD"
# Falsy if the filename doesn't have one (rare; we'll skip the tag in that case).
_VARIANT_RE = re.compile(r'\(([^()]+)\)\.[A-Za-z0-9]+$')


def _candidate_titles(character):
    """Wiki-URL slugs to try, in priority order — canonical name, then
    courtesy name, then aliases. De-duplicated."""
    seen = set()
    for label in character.get_all_name_labels():
        if not label:
            continue
        title = label.strip().replace(' ', '_')
        if not title or title in seen:
            continue
        seen.add(title)
        yield title


def _api_get(params):
    response = requests.get(
        API_URL,
        headers=REQUEST_HEADERS,
        params=params,
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        print(f"  koei API: HTTP {response.status_code} for params={params}")
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _list_images_for_page(title):
    """Return (file_titles, canonical_title). file_titles = [] if the page
    is missing or has no images."""
    data = _api_get({
        'action': 'query',
        'prop': 'images',
        'imlimit': 'max',
        'titles': title,
        'redirects': 1,
        'format': 'json',
    })
    if not data:
        return [], None
    pages = data.get('query', {}).get('pages', {})
    for page in pages.values():
        if 'missing' in page:
            return [], None
        canonical = page.get('title', title)
        files = [img['title'] for img in page.get('images', []) if 'title' in img]
        return files, canonical
    return [], None


def _resolve_image_urls(file_titles):
    """Map {file_title -> url} via batched imageinfo calls."""
    result = {}
    for i in range(0, len(file_titles), IMAGES_BATCH_SIZE):
        chunk = file_titles[i:i + IMAGES_BATCH_SIZE]
        data = _api_get({
            'action': 'query',
            'prop': 'imageinfo',
            'iiprop': 'url',
            'titles': '|'.join(chunk),
            'format': 'json',
        })
        if not data:
            continue
        pages = data.get('query', {}).get('pages', {})
        for page in pages.values():
            title = page.get('title')
            info = page.get('imageinfo', [])
            if title and info and info[0].get('url'):
                result[title] = info[0]['url']
    return result


def _strip_file_prefix(file_title):
    if file_title.lower().startswith('file:'):
        return file_title[5:].lstrip()
    return file_title


def _filter_to_character(file_titles, character):
    """Keep only files whose basename (sans 'File:') starts with one of the
    character's name labels. Filters out unrelated assets like wiki UI icons."""
    name_labels = [
        label.strip().lower() for label in character.get_all_name_labels()
        if label and label.strip()
    ]
    if not name_labels:
        return []
    matches = []
    for title in file_titles:
        base = _strip_file_prefix(title).lower()
        if any(base.startswith(label) for label in name_labels):
            matches.append(title)
    return matches


def _extract_variant(file_title):
    base = _strip_file_prefix(file_title).strip()
    m = _VARIANT_RE.search(base)
    return m.group(1).strip() if m else ""


def scrape(character, max_images=None):
    """List + filter + resolve every Koei portrait for the character.

    Returns a list of ScrapedImage. Empty list if no candidate title yielded
    a real page or no filename matched the character's names."""
    for title in _candidate_titles(character):
        file_titles, canonical = _list_images_for_page(title)
        if canonical is None:
            continue
        matches = _filter_to_character(file_titles, character)
        if not matches:
            continue
        matches.sort()   # deterministic ordering across runs
        if max_images is not None:
            matches = matches[:max_images]
        urls = _resolve_image_urls(matches)
        if not urls:
            continue
        page_url = WIKI_URL + canonical.replace(' ', '_')
        return [
            ScrapedImage(
                image_url=urls[file_title],
                source_url=page_url,
                source_site=SITE_NAME,
                description="",
                variant_tag=_extract_variant(file_title),
            )
            for file_title in matches
            if file_title in urls
        ]
    return []
