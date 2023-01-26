import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from os import path, remove as remove_file
from distutils.dir_util import remove_tree
import zipfile
from datetime import datetime
from os import path
from queue import Empty, Queue

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from metacheck.model import Base, LinkMap, Url


requests_session = requests.Session()


def remove_trailing_slash(url):
    if url[-1:] == "/":
        url = url[:-1]

    if "#" in url:
        url = url[: url.find("#")]

    return url

SITE = ""
graphs = ""

engine = create_engine(
    "sqlite:///database.db", connect_args={"check_same_thread": False}
)
database_session_factory = sessionmaker(bind=engine)
database_session = scoped_session(database_session_factory)

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


crawl_queue = Queue()

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

            if graphs:
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

    rows = database_session.query(Url).all()
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

    print("\tExtracting files")
    with zipfile.ZipFile(f"{dir}/assets/report.zip", "r") as file:
        file.extractall(f"{dir}/report/")

    with open(f"{dir}/report/index.html", "r") as file:
        template = file.read()

    template = template.replace("{{data}}", raw_json)
    with open(f"{dir}/report/index.html", "w") as file:
        file.write(template)

    print(f"Report created open file://{dir}/report/index.html")


import click


@click.command()
@click.argument("site")
@click.option("--depth", "-d", type=int, help="How deep to follow links.")
@click.option("--graph", "-g", type=int, help="Save data to generate a graph.")
@click.option("--report", "-r", type=int, help="Generate a report.")
def main(site, depth=None, graph=False, report=False):

    SITE = remove_trailing_slash(site)

    crawl_queue.put(SITE)

    graphs = graph

    start_time = datetime.now()
    print(f"Crawling: {SITE}")
    if depth:
        print(f"    Depth: {depth}")
    if graph:
        print("    Generating graph data")

    run_crawler()
    print(f"Finished crawling in {datetime.now() - start_time}")

    if report:
        generate_report()
