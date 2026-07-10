"""Canned chapter HTML used across suites. Mirrors the shape the
scraper produces: <p> paragraphs (some class="quote" / class="poem"),
line breaks inside names, HTML entities, and prose containing
pill-able character/location names."""

# Three paragraphs. Cao Cao appears twice in P1 and once in P3;
# "Mengde" (courtesy) once in P2. Luoyang (location) in P2.
BASIC = (
    '<p>Cao Cao rose in the east. Later, Cao Cao marched west toward the passes.</p>\n'
    '<p>Mengde spoke at Luoyang: the capital must hold.</p>\n'
    '<p>In the end Cao Cao returned home victorious.</p>'
)

# Name split across a line break inside one paragraph (bug 9233c4d),
# and a name followed by a colon (same commit).
LINEBREAK = (
    '<p>They sought out Wang\nYun in the night.</p>\n'
    '<p>Wang Yun: "The plan is set."</p>'
)

# Prefix-name collision: "Cao" alone vs "Cao Cao" (bug e7dbfc2).
PREFIX = '<p>Cao spoke first, then Cao Cao replied, and Cao nodded.</p>'

# HTML entities + a <br> at a word boundary (annotation canonical bug
# c156429): browser textContent of P1 is "Salt & iron duties" while
# strip_html_tags yields "Salt &amp; iron duties" pre-unescape.
ENTITIES = (
    '<p>Salt &amp; iron duties fell to Wang<br>Yun alone.</p>\n'
    '<p>The rest paid a&nbsp;tax in grain.</p>'
)

# Quote + poem classed paragraphs (scraper td class=2 / 3b mapping).
CLASSED = (
    '<p>Plain prose paragraph.</p>\n'
    '<p class="quote">A quoted letter to the throne.</p>\n'
    '<p class="poem">Two kingdoms rise; one falls.</p>'
)

# Four occurrences of the same duplicate name for split-exclusion
# scenarios (Lady Cao, bug 5f6d08a). Occurrences indexed 0..3.
DUPLICATE_NAME = (
    '<p>Lady Cao entered. Lady Cao spoke.</p>\n'
    '<p>Then Lady Cao wept while Lady Cao watched.</p>'
)
