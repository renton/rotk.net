"""Scrape character portraits from koei.fandom.com via the MediaWiki API.

We use api.php instead of scraping the rendered HTML because Fandom's
Fastly layer returns 403 for bot-flavoured User-Agents on regular wiki
pages. The MediaWiki API is intended for programmatic access and
doesn't trip those rules.

Endpoint:
    https://koei.fandom.com/api.php
      ?action=query
      &prop=pageimages
      &piprop=original
      &titles=<Page_Title>
      &redirects=1
      &format=json

`prop=pageimages` with `piprop=original` returns the article's "lead
image" — for a character article that's the infobox portrait, at
native resolution. `redirects=1` follows page redirects server-side
(e.g. romanisation variants), so we don't have to try every alias.
"""
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


def _candidate_titles(character):
    """Page titles to try, in priority order: canonical name first,
    then courtesy name, then each alias. De-duplicated. Underscores
    for spaces (MediaWiki accepts both, but underscores are canonical)."""
    seen = set()
    for label in character.get_all_name_labels():
        if not label:
            continue
        title = label.strip().replace(' ', '_')
        if not title or title in seen:
            continue
        seen.add(title)
        yield title


def _query_image(title):
    """Hit the MediaWiki API for `title`. Returns (image_url, canonical_title)
    or (None, None) if the page is missing or has no lead image."""
    params = {
        'action': 'query',
        'prop': 'pageimages',
        'piprop': 'original',
        'titles': title,
        'redirects': 1,
        'format': 'json',
    }
    response = requests.get(
        API_URL,
        headers=REQUEST_HEADERS,
        params=params,
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        print(f"  koei API: {title} returned HTTP {response.status_code}")
        return None, None

    pages = response.json().get('query', {}).get('pages', {})
    for page in pages.values():
        if 'missing' in page:
            return None, None
        original = page.get('original')
        if original and original.get('source'):
            return original['source'], page.get('title', title)
    return None, None


def scrape(character):
    for title in _candidate_titles(character):
        image_url, canonical = _query_image(title)
        if image_url:
            page_slug = (canonical or title).replace(' ', '_')
            return ScrapedImage(
                image_url=image_url,
                source_url=WIKI_URL + page_slug,
                source_site=SITE_NAME,
                description="",
            )
    return None
