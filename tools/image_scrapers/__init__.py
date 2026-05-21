"""Per-site image scrapers.

Each scraper module exposes:

    SITE_NAME: str         # human-readable, used in Portrait.source_site
    scrape(character) -> ScrapedImage | None

`ScrapedImage` is the common shape returned to the CLI, which handles
downloading and DB writes uniformly across sites.
"""
from dataclasses import dataclass


@dataclass
class ScrapedImage:
    image_url: str       # direct URL of the image file on the source CDN
    source_url: str      # the page URL where the image was found
    source_site: str     # human-readable site name, for credits
    description: str = ""
