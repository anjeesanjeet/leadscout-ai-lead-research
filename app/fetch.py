"""Polite website research: respects robots.txt, reads only a few public pages, extracts readable text."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

# Pages most useful for B2B research, in priority order
LINK_KEYWORDS = ["about", "company", "story", "careers", "jobs", "pricing", "customers", "press", "news",
                 "faq", "help", "support", "shipping", "returns", "services", "work", "case-studies"]


def normalize_website(website: str) -> tuple[str, str]:
    """Returns (https URL of the homepage, bare domain)."""
    w = website.strip()
    if not re.match(r"^https?://", w, re.I):
        w = "https://" + w
    parsed = urlparse(w)
    domain = parsed.netloc.lower().removeprefix("www.")
    return f"{parsed.scheme}://{parsed.netloc}", domain


def html_to_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    description = (meta.get("content") or "").strip() if meta else ""
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if description and description not in text:
        text = f"{description} {text}"
    return title, text


def candidate_links(html: str, base_url: str, domain: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0].split("?")[0].rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc.lower().removeprefix("www.") != domain:
            continue
        path = parsed.path.lower()
        for rank, kw in enumerate(LINK_KEYWORDS):
            if kw in path and path.count("/") <= 3:
                found[url] = min(found.get(url, 99), rank)
                break
    return [u for u, _ in sorted(found.items(), key=lambda kv: kv[1])]


class Fetcher:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            follow_redirects=True, timeout=settings.request_timeout,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en"})
        self._robots: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}"
        if key not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.client.get(key + "/robots.txt")
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots[key] = rp
                else:
                    self._robots[key] = None   # no robots.txt: allowed
            except httpx.HTTPError:
                self._robots[key] = None
        rp = self._robots[key]
        return True if rp is None else rp.can_fetch(self.settings.user_agent, url)

    def get_html(self, url: str) -> str | None:
        if not self.allowed(url):
            return None
        try:
            resp = self.client.get(url)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
            return None
        return resp.text

    def research(self, website: str) -> tuple[list[dict], str | None]:
        """Returns (pages, error). Each page: {kind, url, title, text}."""
        home, domain = normalize_website(website)
        html = self.get_html(home)
        if html is None:
            return [], "homepage unavailable (blocked, robots.txt or not HTML)"
        pages = []
        title, text = html_to_text(html)
        pages.append({"kind": "website", "url": home, "title": title, "text": text[: self.settings.page_char_limit]})
        for url in candidate_links(html, home, domain)[: max(0, self.settings.max_pages - 1)]:
            sub = self.get_html(url)
            if sub:
                t, x = html_to_text(sub)
                if len(x) > 80:
                    pages.append({"kind": "website", "url": url, "title": t, "text": x[: self.settings.page_char_limit]})
        return pages, None


def tavily_search(settings: Settings, query: str, client: httpx.Client | None = None, max_results: int = 3) -> list[dict]:
    """Recent public news/mentions via Tavily. Returns [] when no key is configured or on error."""
    if not settings.tavily_api_key:
        return []
    client = client or httpx.Client(timeout=settings.request_timeout)
    try:
        resp = client.post("https://api.tavily.com/search", json={
            "api_key": settings.tavily_api_key, "query": query, "max_results": max_results,
            "search_depth": "basic", "include_answer": False})
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except (httpx.HTTPError, ValueError):
        return []
    return [{"kind": "search", "url": r.get("url", ""), "title": r.get("title", ""),
             "text": (r.get("content") or "")[: settings.page_char_limit]} for r in results if r.get("content")]
