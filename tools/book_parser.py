import re

from app.models import \
    Chapter, Character

def get_characters_for_chapter(chapter_id):

    all_characters = Character.query.all()

    chapter = Chapter.query.get_or_404(chapter_id)

    chapter_characters = set()

    for character in all_characters:
        name_needles = character.get_all_name_labels()

        pattern = build_needle_pattern(name_needles)

        # Perform a single pass to check if any needle exists in the text
        if pattern.search(chapter.content):
            chapter_characters.add(character)

    return list(chapter_characters)

def build_needle_pattern(name_needles):
    return re.compile(r'\b(' + '|'.join(map(re.escape, name_needles)) + r')(?=\s|,|\.|\!|\?|\'|;|"|-)')

def build_name_ref_html(character):
    html_output = f"<span onclick=\"show_character({ character.id })\" class='character-ref badge rounded-pill' data-character-id='{ character.id }' "

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