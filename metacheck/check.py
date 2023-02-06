import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from distutils.dir_util import remove_tree
from os import path
from queue import Empty, Queue

import click
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


engine = create_engine(
    "sqlite:///database.db", connect_args={"check_same_thread": False}
)
database_session_factory = sessionmaker(bind=engine)
database_session = scoped_session(database_session_factory)

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


crawl_queue = Queue()

visited = []


def process_page(site, page, graph):
    response = requests_session.get(page, timeout=15)

    if response.status_code != 200:
        entry = Url(site=site, url=page, status=response.status_code)
        database_session.add(entry)
        database_session.commit()
        return

    html_page = response.content

    soup = BeautifulSoup(html_page, "html.parser")

    entry = Url(
        site=site,
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
            current_page = site + a.get("href")
        elif a.get("href").startswith(site):
            current_page = a.get("href")

        if current_page:
            current_page = remove_trailing_slash(current_page)
            if (
                current_page not in visited
                and current_page not in crawl_queue.queue
            ):
                crawl_queue.put(current_page)

            if graph:
                if (
                    not database_session.query(LinkMap)
                    .filter(
                        LinkMap.url == page,
                        LinkMap.link == current_page,
                    )
                    .one_or_none()
                ):
                    link_entry = LinkMap(
                        site=site,
                        url=page,
                        link=current_page,
                    )
                    database_session.add(link_entry)
                    database_session.commit()


def run_crawler(site, graph):
    with ThreadPoolExecutor(max_workers=5) as executor:
        while True:
            try:
                page = crawl_queue.get(timeout=15)
                if page not in visited:
                    visited.append(page)
                    executor.submit(process_page, site, page, graph)
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


def generate_report(site):
    print("")
    print("Generating report")

    dir = path.dirname(path.realpath(__file__))

    rows = database_session.query(Url).all()
    results = {"page_count": len(rows), "site": site, "pages": []}
    for row in rows:
        result = row.as_dict()
        if "metadata_json" in result and result["metadata_json"]:
            result["metadata"] = {m[0]: m[1] for m in result["metadata_json"]}

        del result["metadata_json"]
        results["pages"].append(result)

    if args.graph:
        graph_rows = database_session.query(LinkMap).all()
        for row in graph_rows:
            result = row.as_dict()
            results_item = [
                item
                for item in results["pages"]
                if item["url"] == result["link"]
            ]
            if results_item:
                results_item = results_item[0]
                if "links_from" not in results_item:
                    results_item["links_from"] = []
                results_item["links_from"].append(result["url"])

    raw_json = json.dumps(results)

    template = ""

    try:
        remove_tree(f"{dir}/report")
    except Exception:
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


@click.command()
@click.argument("site")
@click.option("-d", "--depth", type=int, help="How deep to follow links.")
@click.option(
    "-g", "--graph", is_flag=True, help="Save data to generate a graph."
)
@click.option("-r", "--report", is_flag=True, help="Generate a report.")
def main(site, depth=None, graph=False, report=False):
    site = remove_trailing_slash(site)
    crawl_queue.put(site)

    start_time = datetime.now()
    print(f"Crawling: {site}")
    if depth:
        print(f"    Depth: {depth}")
    if graph:
        print("    Generating graph data")

    run_crawler(site, graph)
    print(f"Finished crawling in {datetime.now() - start_time}")

    if report:
        generate_report(site)
