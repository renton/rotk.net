import requests, re
from bs4 import BeautifulSoup

from app import db

ROTK_BOOK_PATH = "https://threekingdoms.com"
ROTK_BOOK_AUTHOR = "Luo Guanzhong"
ROTK_BOOK_DATE = "circa 1300-1400"

ROTK_BOOK_TRANSLATOR = "C. H. Brewitt-Taylor"
ROTK_BOOK_EDITOR = "Khang Nguyen"
ROTK_BOOK_COMMENTATOR = "Dr Rafe de Crespigny"

ROTK_BOOK_EDITION = "Online fifth edition"

ROTK_NUM_CHAPTERS = 120

def clean_text(text):
    if text:  # Check if text is not None
        # Normalize Unicode, remove non-ASCII characters, strip whitespace
        text = text.replace('\r', '').replace('\n', '').replace('\t', '')
        text = ' '.join(text.split())  # Collapse multiple spaces
        return text
    return ""

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
                print(td_classes)
                raise Exception("TOO BIG")

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


