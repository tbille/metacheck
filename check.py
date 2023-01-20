import argparse
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from model import Base, Url

parser = argparse.ArgumentParser(
    description=(
        "Metadata checker for your website. "
        "This program will generate a sqlite database "
        "with all endpoints and the metadata of your site"
    )
)

parser.add_argument("site", help="Your website.")

args = parser.parse_args()

if not args.site:
    print("You must add add a URL to parse.")
    exit(1)

SITE = args.site

engine = create_engine("sqlite:///database.db")
Session = sessionmaker(bind=engine)
session = Session()
Base.metadata.create_all(engine)

PAGES_VISITATED = []


def crawler(page):
    PAGES_VISITATED.append(page)
    response = requests.get(page)

    if response.status_code != 200:
        entry = Url(site=SITE, url=page, status=response.status_code)
        session.add(entry)
        session.commit()
        return

    html_page = response.content

    soup = BeautifulSoup(html_page, "html.parser")

    entry = Url(
        site=SITE,
        url=page,
        status=response.status_code,
        metadata_json=get_page_info(soup),
    )
    session.add(entry)
    session.commit()

    for a in soup.find_all("a"):
        current_page = ""
        if not a.get("href"):
            continue

        if a.get("href").startswith("/"):
            current_page = SITE + a.get("href")
        elif a.get("href").startswith(SITE):
            current_page = a.get("href")

        if current_page:
            if "#" in current_page:
                current_page = current_page[: current_page.find("#")]
            if current_page not in PAGES_VISITATED:
                crawler(current_page)


def get_page_info(soup):
    metadata = []
    for meta in soup.find_all("meta"):
        if meta.get("name"):
            metadata.append((meta.get("name"), meta.get("content")))

        if meta.get("property"):
            metadata.append((meta.get("property"), meta.get("content")))

    return metadata


crawler(SITE)
