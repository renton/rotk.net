"""Scrape character portraits from koei.fandom.com.

URL pattern: https://koei.fandom.com/wiki/<Name_With_Underscores>

If the primary URL 404s (or has no matching image), we fall through to the
character's courtesy name and aliases. The image we want is the first
<img> inside an <a class="mw-file-description image"> on the page.
"""
import urllib.parse

import requests
from bs4 import BeautifulSoup

from . import ScrapedImage


SITE_NAME = "Koei Wiki (Fandom)"
BASE_URL = "https://koei.fandom.com/wiki/"
USER_AGENT = (
    "rotk.net-scraper/1.0 "
    "(+https://rotk.net; an annotated Romance of the Three Kingdoms edition)"
)
REQUEST_HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT_SECONDS = 15


def _candidate_slugs(character):
    """Yield wiki-URL slugs to try, in priority order: canonical name first,
    then courtesy name, then each alias. De-duplicated."""
    seen = set()
    for label in character.get_all_name_labels():
        if not label:
            continue
        slug = label.strip().replace(' ', '_')
        if not slug or slug in seen:
            continue
        seen.add(slug)
        yield slug


def _fetch(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=TIMEOUT_SECONDS)
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        # 429 / 503 / etc. — surface to the caller log; treat as miss for now.
        print(f"  koei: {url} returned HTTP {response.status_code}")
        return None
    return response.text


def _extract_image(html):
    """Return the first image src found inside an <a class='mw-file-description image'>,
    or None. Prefers data-src (Fandom's lazy-load attribute) over src."""
    soup = BeautifulSoup(html, 'html.parser')

    for anchor in soup.find_all('a'):
        classes = anchor.get('class') or []
        if 'mw-file-description' in classes and 'image' in classes:
            img = anchor.find('img')
            if not img:
                continue
            src = img.get('data-src') or img.get('src')
            if src:
                return src
    return None


def scrape(character):
    """Try each candidate slug until one yields an image. Returns a
    ScrapedImage or None if no slug produced one."""
    for slug in _candidate_slugs(character):
        url = BASE_URL + urllib.parse.quote(slug, safe='_')
        html = _fetch(url)
        if html is None:
            continue
        image_url = _extract_image(html)
        if image_url:
            return ScrapedImage(
                image_url=image_url,
                source_url=url,
                source_site=SITE_NAME,
                description="",
            )
    return None
