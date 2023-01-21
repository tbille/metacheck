import argparse
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from model import Base, Url, LinkMap

parser = argparse.ArgumentParser(
    description=(
        "Metadata checker for your website. "
        "This program will generate a sqlite database "
        "with all endpoints and the metadata of your site"
    )
)

parser.add_argument("site", help="Your website.")
parser.add_argument(
    "-d", "--depth", help="How deep to follow links.", required=False, type=int
)
parser.add_argument(
    "-g",
    "--graph",
    help="Save data to generate a graph.",
    required=False,
    action="store_true",
)

args = parser.parse_args()

if not args.site:
    print("You must add add a URL to parse.")
    exit(1)


def remove_trailing_slash(url):
    if url[-1:] == "/":
        url = url[:-1]
    return url


SITE = remove_trailing_slash(args.site)

engine = create_engine("sqlite:///database.db")
Session = sessionmaker(bind=engine)
session = Session()
Base.metadata.create_all(engine)

run_time = datetime.utcnow().isoformat()


def crawler(page, depth):
    # Remove trailing slashes
    page = remove_trailing_slash(page)

    response = requests.get(page)

    if response.status_code != 200:
        entry = Url(
            site=SITE, run_time=run_time, url=page, status=response.status_code
        )
        session.add(entry)
        session.commit()
        return

    html_page = response.content

    soup = BeautifulSoup(html_page, "html.parser")

    entry = Url(
        site=SITE,
        run_time=run_time,
        url=page,
        status=response.status_code,
        metadata_json=get_page_info(soup),
    )
    session.add(entry)
    session.commit()

    if args.depth and depth == args.depth:
        return

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

            current_page = remove_trailing_slash(current_page)

            if args.graph:
                if (
                    not session.query(LinkMap)
                    .filter(
                        LinkMap.url == page,
                        LinkMap.link == current_page,
                        LinkMap.run_time == run_time,
                    )
                    .one_or_none()
                ):
                    link_entry = LinkMap(
                        site=SITE,
                        run_time=run_time,
                        url=page,
                        link=current_page,
                    )
                    session.add(link_entry)
                    session.commit()

            if (
                not session.query(Url)
                .filter(Url.url == current_page, Url.run_time == run_time)
                .one_or_none()
            ):
                crawler(current_page, depth + 1)


def get_page_info(soup):
    metadata = []

    title = soup.find("title")

    if title:
        metadata.append(("title", title.string))

    for meta in soup.find_all("meta"):
        if meta.get("name"):
            metadata.append((meta.get("name"), meta.get("content")))

        if meta.get("property"):
            metadata.append((meta.get("property"), meta.get("content")))

    for meta in soup.find_all("link"):
        # don't get things like text/css or image/x-icon
        if not meta.get("type"):
            rel = meta.get("rel")
            if not rel in ["preconnect", "preload"]:
                metadata.append((meta.get("rel")[0], meta.get("href")))

    return metadata


start_time = datetime.now()
print(f"Crawling: {SITE}")
if args.depth:
    print(f"    Depth: {args.depth}")
if args.graph:
    print("    Generating graph data")

crawler(SITE, 0)
print(f"Finished in {datetime.now() - start_time}")
