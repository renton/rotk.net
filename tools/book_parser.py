import re

from app.models import \
    Chapter, Character

def get_characters_for_chapter(chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)

    # Prefer the precomputed M2M (populated by `flask build-chapter-character-association`).
    cached = list(chapter.characters)
    if cached:
        return cached

    return scan_chapter_for_characters(chapter)


def scan_chapter_for_characters(chapter):
    """Regex-scan the chapter text against every character's names/aliases.

    Slow — O(N_characters) regex compilations + scans per chapter. Used as
    a fallback when the chapter_character association table is empty.
    """
    all_characters = Character.query.all()
    chapter_characters = set()

    for character in all_characters:
        name_needles = character.get_all_name_labels()
        pattern = build_needle_pattern(name_needles)
        if pattern.search(chapter.content):
            chapter_characters.add(character)

    return list(chapter_characters)

def build_needle_pattern(name_needles):
    return re.compile(r'\b(' + '|'.join(map(re.escape, name_needles)) + r')(?=\s|,|\.|\!|\?|\'|;|"|-)')

def build_name_ref_html(character):
    html_output = f"<span class='character-ref badge rounded-pill' data-character-id='{ character.id }' "

    if character.latest_faction is not None:
        html_output += f"data-faction-id='{ character.latest_faction.id }'"

        html_output += f" style='"
        if character.latest_faction.bg_colour not in ["", character.latest_faction.default_colour]:
            html_output += f"background-color:{character.latest_faction.bg_colour};"
        else:
            html_output += f"background-color:#000;"
        
        if character.latest_faction.font_colour:
            html_output += f"color:{character.latest_faction.font_colour};"

        if character.latest_faction.border_colour not in ["", character.latest_faction.default_colour]:
            html_output += f"border:2px solid {character.latest_faction.border_colour};"
        
        html_output += "'"

    html_output += f">{ character.name }</span>"

    return html_output