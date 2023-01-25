import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from os import path, remove as remove_file
from distutils.dir_util import remove_tree
import tarfile
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

    if "#" in url:
        url = url[: url.find("#")]

    return url


SITE = remove_trailing_slash(args.site)

engine = create_engine(
    "sqlite:///database.db", connect_args={"check_same_thread": False}
)
database_session_factory = sessionmaker(bind=engine)
database_session = scoped_session(database_session_factory)

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


crawl_queue = Queue()
crawl_queue.put(SITE)

visited = []


def process_page(page):
    response = requests_session.get(page, timeout=15)

    if response.status_code != 200:
        entry = Url(site=SITE, url=page, status=response.status_code)
        database_session.add(entry)
        database_session.commit()
        return

    html_page = response.content

    soup = BeautifulSoup(html_page, "html.parser")

    entry = Url(
        site=SITE,
        url=page,
        status=response.status_code,
        metadata_json=get_page_info(soup),
    )
    database_session.add(entry)
    database_session.commit()

    for a in soup.find_all("a"):
        current_page = ""
        if not a.get("href"):
            continue

        if a.get("href").startswith("/"):
            current_page = SITE + a.get("href")
        elif a.get("href").startswith(SITE):
            current_page = a.get("href")

        if current_page:
            current_page = remove_trailing_slash(current_page)
            if (
                current_page not in visited
                and current_page not in crawl_queue.queue
            ):
                crawl_queue.put(current_page)

            if args.graph:
                if (
                    not database_session.query(LinkMap)
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
                    database_session.add(link_entry)
                    database_session.commit()


def run_crawler():
    with ThreadPoolExecutor(max_workers=5) as executor:
        while True:
            try:
                page = crawl_queue.get(timeout=15)
                if page not in visited:
                    visited.append(page)
                    executor.submit(process_page, page)
            except Empty:
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


def generate_report():
    print("")
    print("Generating report")

    dir = path.dirname(path.realpath(__file__))

    rows = session.query(Url).all()
    results = {"page_count": len(rows), "site": SITE, "pages": []}
    for row in rows:
        result = row.as_dict()
        if "metadata_json" in result and result["metadata_json"] != None:
            result["metadata"] = {m[0]: m[1] for m in result["metadata_json"]}

        del result["metadata_json"]
        results["pages"].append(result)

    raw_json = json.dumps(results)
    template = ""

    try:
        remove_tree(f"{dir}/report")
    except:
        pass

    print("Finding latest version of metacheck-report")
    # get latest version of metacheck-report
    response = requests.get(
        "https://api.github.com/repos/Lukewh/metacheck-report/releases/latest"
    ).json()

    report_url = response["assets"][0]["browser_download_url"]
    report_version = response["tag_name"]
    print(f"\tDownloading: {report_version}")
    report_tar = requests.get(report_url)

    with open(f"{dir}/metacheck-report-{report_version}.tar.xz", "wb") as file:
        file.write(report_tar.content)

    print("\tExtracting files")
    with tarfile.open(
        f"{dir}/metacheck-report-{report_version}.tar.xz"
    ) as file:
        file.extractall(f"{dir}/report/")

    print("\tDeleting download")
    remove_file(f"{dir}/metacheck-report-{report_version}.tar.xz")

    with open(f"{dir}/report/index.html", "r") as file:
        template = file.read()

    template = template.replace("{{data}}", raw_json)
    with open(f"{dir}/report/index.html", "w") as file:
        file.write(template)

    print(f"Report created open file://{dir}/report/index.html")


start_time = datetime.now()
print(f"Crawling: {SITE}")
if args.depth:
    print(f"    Depth: {args.depth}")
if args.graph:
    print("    Generating graph data")

run_crawler()
print(f"Finished crawling in {datetime.now() - start_time}")

if args.report:
    generate_report()
