"""Fetch a single celma.org.cn detail page and pull out title / publish date /
body text / PDF attachment links.

Unlike MOF's announcements (plain HTML text), celma.org.cn detail pages carry
almost no body text -- the actual disclosure content lives entirely in PDF
attachment(s) linked from a '附件' (attachments) block, so this parser's main
job is finding those attachment URLs; field extraction happens later against
the downloaded PDFs (see pdf_extract.py / extract_announcement.py / extract_plan.py).
"""
import datetime
import re

from bs4 import BeautifulSoup

from .http_client import fetch

WHITESPACE_RE = re.compile(r"\s+")
DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def parse_article(url: str, use_cache: bool = True) -> dict:
    html = fetch(url, use_cache=use_cache)
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else None

    pub_date = None
    inf = soup.find(class_="secondPage-content-inf")
    if inf:
        m = DATE_RE.search(inf.get_text(" ", strip=True))
        if m:
            pub_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    body_el = soup.find(class_="content-txt")
    body_text = body_el.get_text("\n", strip=True) if body_el else ""

    attachments = []
    fj = soup.find(class_="content-fj")
    if fj:
        for a in fj.find_all("a", href=True):
            href = a["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            attachments.append({
                "url": href,
                "name": a.get("title") or a.get_text(strip=True),
            })

    return {
        "url": url,
        "title": title,
        "pub_date": pub_date,
        "body_text": body_text,
        "attachments": attachments,
        "parse_ok": bool(title and pub_date),
    }
