import requests, re, string
from bs4 import BeautifulSoup

from app.models import Character, Role, Faction

from app import db

ROTK_BOOK_PATH = "https://threekingdoms.com"
ROTK_BOOK_AUTHOR = "Luo Guanzhong"
ROTK_BOOK_DATE = "circa 1300-1400"

ROTK_BOOK_TRANSLATOR = "C. H. Brewitt-Taylor"
ROTK_BOOK_EDITOR = "Khang Nguyen"
ROTK_BOOK_COMMENTATOR = "Dr Rafe de Crespigny"

ROTK_BOOK_EDITION = "Online fifth edition"

ROTK_NUM_CHAPTERS = 120

ROTK_CHARACTER_PATH = "https://en.wikipedia.org/wiki/List_of_people_of_the_Three_Kingdoms"


ROTK_NUM_CHAPTERS = 120

def clean_text(text):
    if text:  # Check if text is not None
        # Normalize Unicode, remove non-ASCII characters, strip whitespace
        text = text.replace('\r', '').replace('\n', '').replace('\t', '')
        text = ' '.join(text.split())  # Collapse multiple spaces
        text = text.lstrip()
        text = text.rstrip()
        return text
    return ""

def remove_html_tags(text):
    clean_text = re.sub(r'<.*?>', '', text)
    return clean_text

def scrape_rotk_book():
    chapters = []

    for chapter in range(ROTK_NUM_CHAPTERS):
        chapters.append(scrape_chapter(chapter+1))

    return chapters

def build_chapter_url(chapter_number):
    converted_chapter_number = f"{chapter_number:03}"
    return f"{ROTK_BOOK_PATH}/{converted_chapter_number}.htm"

def scrape_chapter(chapter_number):
    chapter_url = build_chapter_url(chapter_number)
    print(f">>> {chapter_url}")

    response = requests.get(chapter_url)

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')

        chapter_content = ""

        chapter_title = soup.find('font', class_='t12b')

        for tag in chapter_title.find_all():
            tag.decompose()          

        chapter_html = soup.find('table', id='txt_content')

        paragraphs = chapter_html.find_all('td', {'class':['1', '3b']})

        for paragraph in paragraphs:
            
            paragraph.name = "p"

            td_classes = paragraph.get('class', [])

            if len(td_classes) > 1 and ('1' not in td_classes or '3b' not in td_classes):
                raise Exception("TOO BIG ", td_classes)

            for tag in soup.find_all('a', class_='1'):
                tag.decompose()

            if td_classes[0] == "1":
                del paragraph['class']
            elif td_classes[0] == "3b":
                paragraph['class'] = "poem"

            chapter_content += f"{re.sub("<p> ", "<p>", str(paragraph))}\n"            

        return(
            clean_text(chapter_title.get_text()).replace(";","; <br>"),
            chapter_content
        )

    else:
        print(f"{response.status_code} Failed to retrieve chapter.")
        return ""

def scrape_rotk_characters():
    characters = []
    factions = set()
    roles = set()

    for letter in list(string.ascii_uppercase):
        page_characters, page_factions, page_roles = scrape_rotk_character_page(letter)

        characters.extend(page_characters)

        factions = factions.union(page_factions)
        roles = roles.union(page_roles)

    return characters, factions, roles

def build_page_url(letter):
    return f"{ROTK_CHARACTER_PATH}_({letter})"

def split_cell_sections(td):
    decoded_cell = clean_text(td.decode_contents())

    if decoded_cell == "":
        return []
    elif "<p>" in decoded_cell:
        decoded_cell = decoded_cell.replace("</p>","")
        name_sections = decoded_cell.split("<p>")
    elif "<br/>" in decoded_cell:
        name_sections = decoded_cell.split("<br/>")
    elif "<br>" in decoded_cell:
        name_sections = decoded_cell.split("<br>")
    else:
        print(decoded_cell)
        name_sections = [decoded_cell]
        #raise Exception("BAD DATA")

    return name_sections
    

# Maps a lowercased Wikipedia header substring to the logical column we
# care about. Order matters — first match wins, so put more specific keys
# (e.g. "courtesy", "ancestral") before general ones whose substring shows
# up inside them ("name", "home"). Wikipedia headers seen in the wild
# include "Courtesy name" (matches both "courtesy" and "name") and
# "Ancestral home (present-day location)" (matches both "ancestral" and
# "home").
COLUMN_MATCHERS = [
    ('courtesy', 'courtesy_name'),
    ('ancestral', 'ancestral_home'),
    ('name', 'name'),
    ('born', 'birth_date'),
    ('birth', 'birth_date'),
    ('died', 'death_date'),
    ('death', 'death_date'),
    ('home', 'ancestral_home'),
    ('role', 'role'),
    ('allegiance', 'faction'),
    ('faction', 'faction'),
]


def _classify_header(text):
    lower = text.lower()
    for needle, kind in COLUMN_MATCHERS:
        if needle in lower:
            return kind
    return None


def _parse_table_headers(table):
    """Return a list of logical column kinds in order. Indexes line up with
    the `<td>` cells in each data row. Unknown columns get None."""
    header_row = table.find('tr')
    if header_row is None:
        return []
    return [_classify_header(clean_text(th.get_text())) for th in header_row.find_all('th')]


def scrape_rotk_character_page(letter):
    page_url = build_page_url(letter)

    page_characters = []
    page_factions = set()
    page_roles = set()

    response = requests.get(page_url)

    soup = BeautifulSoup(response.text, 'html.parser')

    print(f">>> {letter}")
    table = soup.find('table', class_='wikitable')
    if not table:
        return [], [], []

    column_kinds = _parse_table_headers(table)
    if not column_kinds:
        print(f"!!! {letter}: could not parse column headers")
        return [], [], []

    character_rows = table.find_all('tr')

    for character_row in character_rows:

        # skip header rows
        if character_row.find_all('th'):
            continue

        new_character_data = {
            'roles': [],
            'factions': [],
            'aliases': '',
            'chinese_name': '',
            'courtesty_name': '',
            'chinese_courtesty_name': '',
            'birth_date': '',
            'death_date': '',
            'ancestral_home': '',
            'latest_faction': None,
        }

        cells = character_row.find_all('td')
        seen_faction_column = False

        for i, td in enumerate(cells):
            kind = column_kinds[i] if i < len(column_kinds) else None
            if kind is None:
                continue

            if kind == 'name':
                name_sections = split_cell_sections(td)
                if name_sections:
                    name_parts = remove_html_tags(clean_text(name_sections[0])).split('/')
                    new_character_data['name'] = clean_text(name_parts[0])
                    if len(name_parts) > 1:
                        new_character_data['aliases'] = ', '.join(clean_text(p) for p in name_parts[1:])
                if len(name_sections) > 1:
                    new_character_data['chinese_name'] = remove_html_tags(clean_text(name_sections[1]))

            elif kind == 'courtesy_name':
                name_sections = split_cell_sections(td)
                if name_sections:
                    new_character_data['courtesty_name'] = remove_html_tags(clean_text(name_sections[0]))
                if len(name_sections) > 1:
                    new_character_data['chinese_courtesty_name'] = remove_html_tags(clean_text(name_sections[1]))

            elif kind == 'birth_date':
                new_character_data['birth_date'] = clean_text(td.text)

            elif kind == 'death_date':
                new_character_data['death_date'] = clean_text(td.text)

            elif kind == 'ancestral_home':
                new_character_data['ancestral_home'] = clean_text(td.text)

            elif kind == 'role':
                for row_role in clean_text(td.text).split(','):
                    role_string = clean_text(row_role.lower())
                    if role_string:
                        page_roles.add(role_string)
                        new_character_data['roles'].append(role_string)

            elif kind == 'faction':
                row_factions = [clean_text(f) for f in clean_text(td.text).split(',')]
                row_factions = [f for f in row_factions if f]
                for faction_string in row_factions:
                    page_factions.add(faction_string)
                    new_character_data['factions'].append(faction_string)
                # First faction column on the row is treated as "current".
                if not seen_faction_column and row_factions:
                    new_character_data['latest_faction'] = row_factions[0]
                seen_faction_column = True

        page_characters.append(new_character_data)

    return page_characters, page_factions, page_roles

