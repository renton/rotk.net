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
        return text
    return ""

def remove_html_tags(text):
    clean_text = re.sub(r'<.*?>', '', text)
    return clean_text

def scrape_rotk_book():
    chapters = []

    for chapter in range(10):
        chapters.append(scrape_chapter(chapter+1))

    return chapters

def build_chapter_url(chapter_number):
    converted_chapter_number = f"{chapter_number:03}"
    return f"{ROTK_BOOK_PATH}/{converted_chapter_number}.htm"

def scrape_chapter(chapter_number):
    chapter_url = build_chapter_url(chapter_number)

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
            clean_text(chapter_title.get_text()),
            chapter_content
        )

    else:
        print(f"{response.status_code} Failed to retrieve chapter.")
        return ""

def scrape_rotk_characters():
    characters = []
    factions = set()
    roles = set()

    for letter in ['A']: #list(string.ascii_uppercase):
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
    

def scrape_rotk_character_page(letter):
    page_url = build_page_url(letter)

    page_characters = []
    page_factions = set()
    page_roles = set()

    response = requests.get(page_url)

    soup = BeautifulSoup(response.text, 'html.parser')

    print("*******************", letter)
    table = soup.find('table', class_='wikitable')
    if not table:
        return [], [], []

    character_rows = table.find_all('tr')

    for character_row in character_rows:

        # skip header row
        if len(character_row.find_all('th')) > 0:
            continue

        new_character_data = {
            'roles' : [],
            'factions' : []
        }       

        # TODO if / in name, need to save rest as aliases
        for i, td in enumerate(character_row.find_all('td')):
            if i == 0:
                # name
                name_sections = split_cell_sections(td)
                
                if len(name_sections) > 0:
                    new_character_data['name'] = remove_html_tags(clean_text(name_sections[0]))

                if len(name_sections) > 1:
                    new_character_data['chinese_name'] = remove_html_tags(clean_text(name_sections[1]))
                else:
                    new_character_data['chinese_name'] = ""
                
            elif i == 1:
                # courtesty name
                name_sections = split_cell_sections(td)
                
                if len(name_sections) > 0:
                    new_character_data['courtesty_name'] = remove_html_tags(clean_text(name_sections[0]))
                else:
                    new_character_data['courtesty_name'] = ""

                if len(name_sections) > 1:
                    new_character_data['chinese_courtesty_name'] = remove_html_tags(clean_text(name_sections[1]))
                else:
                    new_character_data['chinese_courtesty_name'] = ""

            elif i == 2:
                # birth date
                birth_date_text = clean_text(td.text)
                if birth_date_text == "":
                    new_character_data['birth_date'] = ""
                else:
                    new_character_data['birth_date'] = birth_date_text
            elif i == 3:
                # death date
                death_date_text = clean_text(td.text)
                if death_date_text == "":
                    new_character_data['death_date'] = ""
                else:
                    new_character_data['death_date'] = death_date_text
            elif i == 4:
                # ancestral home
                new_character_data['ancestral_home'] = clean_text(td.text)
            elif i == 5:
                # role
                row_roles = clean_text(td.text).split(",")

                for row_role in row_roles:
                    if row_role != "":
                        role_string = clean_text(row_role.lower())
                        page_roles.add(role_string)
                        new_character_data['roles'].append(role_string)

            elif i == 6 or i == 7:
                # faction
                row_factions = clean_text(td.text).split(",")

                for row_faction in row_factions:
                    if row_faction != "":
                        faction_string = clean_text(row_faction)
                        page_factions.add(faction_string)
                        new_character_data['factions'].append(faction_string)

        page_characters.append(new_character_data)

    return page_characters, page_factions, page_roles

