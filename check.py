import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from os import path
from queue import Empty, Queue

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from model import Base, LinkMap, Url

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

parser.add_argument(
    "-r",
    "--report",
    help="Generate a report.",
    required=False,
    action="store_true",
)

args = parser.parse_args()

if not args.site:
    print("You must add add a URL to parse.")
    exit(1)


requests_session = requests.Session()


def remove_trailing_slash(url):
    if url[-1:] == "/":
        url = url[:-1]
    return url


SITE = remove_trailing_slash(args.site)

engine = create_engine(
    "sqlite:///database.db", connect_args={"check_same_thread": False}
)
session_factory = sessionmaker(bind=engine)
session = scoped_session(session_factory)
Base.metadata.create_all(engine)


crawl_queue = Queue()
crawl_queue.put(SITE)

pool = ThreadPoolExecutor(max_workers=5)

visited = set()


def get_page(url):
    try:
        return requests_session.get(url)
    except requests.RequestException:
        return


def process_page(res):
    response = res.result()
    if not response:
        return

    page = remove_trailing_slash(response.url)
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

            current_page = remove_trailing_slash(current_page)
            if current_page not in crawl_queue.queue and current_page not in visited:
                crawl_queue.put(current_page)

            if args.graph:
                if (
                    not session.query(LinkMap)
                    .filter(
                        LinkMap.url == page,
                        LinkMap.link == current_page,
                    )
                    .one_or_none()
                ):
                    link_entry = LinkMap(
                        site=SITE,
                        url=page,
                        link=current_page,
                    )
                    session.add(link_entry)
                    session.commit()


def run_crawler():
    while True:
        try:
            # Remove trailing slashes
            page = remove_trailing_slash(crawl_queue.get(timeout=10))
            if page not in visited:
                visited.add(page)
                job = pool.submit(get_page, page)
                job.add_done_callback(process_page)
        except Empty:
            print("Empty")
            return
        except Exception as e:
            print(e)
            continue


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
            if rel and set(rel).isdisjoint(["preconnect", "preload"]):
                metadata.append((meta.get("rel")[0], meta.get("href")))

    return metadata


start_time = datetime.now()
print(f"Crawling: {SITE}")
if args.depth:
    print(f"    Depth: {args.depth}")
if args.graph:
    print("    Generating graph data")

run_crawler()
print(f"Finished crawling in {datetime.now() - start_time}")

if not args.report:
    exit()

print("")
print("Generating report")

dir = path.dirname(path.realpath(__file__))

rows = session.query(Url).all()
results = {"page_count": len(rows), "site": SITE, "pages": []}
for row in rows:
    result = row.as_dict()
    if "metadata_json" in result and result["metadata_json"]:
        result["metadata"] = {m[0]: m[1] for m in result["metadata_json"]}

    del result["metadata_json"]
    results["pages"].append(result)

raw_json = json.dumps(results)
template = ""
with open(f"{dir}/assets/report/index.html", "r") as file:
    template = file.read().replace("{{data}}", raw_json)

with open(f"{dir}/index.html", "w+") as file:
    file.write(template)

print(f"Report created open {dir}/report.html")
