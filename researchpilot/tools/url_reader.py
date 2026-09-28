"""URL reader and content extractor tool for ResearchPilot.

Fetches web pages, extracts main body text, removes HTML boilerplate,
handles HTTP failures, and supports deterministic failure simulation.
Provides standard library fallbacks when external pip packages are absent.
"""
from __future__ import annotations
import time
import urllib.parse
import urllib.request
import re
from typing import Dict, Any

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from . import ToolResult, ToolExecutionError

MIN_CONTENT_LENGTH = 80

CATEGORY_SLUGS = {
    "", "news", "news/", "world", "world/", "world-news", "world-news/",
    "news/world", "news/world/", "international", "international/",
    "politics", "politics/", "business", "business/", "hub", "index.html"
}

GENERIC_TITLES = {
    "world news", "bbc world news", "reuters world news", "associated press international news wire",
    "world - bbc news", "latest news", "breaking news", "international headlines and global developments",
    "breaking global news & diplomatic events", "ap news - world news", "world news wire", "home"
}

NAV_WORDS = {
    "home", "video", "world", "sport", "business", "tech", "science", "entertainment",
    "health", "climate", "weather", "sounds", "privacy", "cookies", "cookie settings",
    "terms of use", "accessibility", "menu", "search", "sections", "top stories",
    "more menu", "close menu", "skip to content", "your account", "in pictures", "newsbeat"
}

PORTAL_DESCRIPTIONS = [
    "breaking international news, in-depth reports, and live analysis",
    "cover diplomacy, multilateral accords, geopolitical crises",
    "covers diplomacy, multilateral accords",
    "comprehensive worldwide reporting on international diplomacy",
    "verified global news wire reporting on world leadership",
    "portal overview", "category landing page", "landing page descriptions"
]


def is_article_content(url: str, title: str, content: str) -> tuple[bool, str]:
    """Deterministically distinguish an individual news article from a portal/category landing page.
    
    Returns:
        (is_article: bool, reason: str)
    """
    clean_url = (url or "").strip().lower()
    clean_title = (title or "").strip().lower()
    clean_content = (content or "").strip()
    content_lower = clean_content.lower()

    # 1. URL Path Inspection
    try:
        parsed = urllib.parse.urlparse(clean_url)
        path = parsed.path.strip("/")
        # If path is empty or matches known category landing page patterns
        if path in CATEGORY_SLUGS or path == "":
            return False, f"URL '{url}' points to a category hub or domain root, not an individual article."
        
        # Specific known portal hubs
        if re.search(r"/(news|world|world-news)/?$", clean_url) and not re.search(r"/(articles|article|live|\d{4})/", clean_url):
            return False, f"URL '{url}' is a category section landing page."
    except Exception:
        pass

    # 2. Generic Portal Title Inspection
    for gen in GENERIC_TITLES:
        if gen in clean_title and len(clean_title) <= len(gen) + 20:
            return False, f"Title '{title}' is a generic section/portal title rather than an article headline."

    # 3. Meta Portal Description Detection
    for pd in PORTAL_DESCRIPTIONS:
        if pd in content_lower:
            return False, f"Content contains portal boilerplate/overview description: '{pd}'."

    # 4. Navigation & Page Shell Detection
    # If the text is dominated by navigation menu items
    words = [w.strip() for w in re.split(r"[\s,;|]+", content_lower) if len(w.strip()) > 2]
    if len(words) > 0:
        nav_match_count = sum(1 for w in words if w in NAV_WORDS)
        nav_ratio = nav_match_count / len(words)
        if nav_ratio > 0.20 and len(words) < 250:
            return False, f"Content consists primarily of site navigation menus ({nav_match_count} nav tokens)."

    # 5. Narrative Substance & Article Verification
    # For full extracted content (>250 chars), require multiple narrative sentences
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", clean_content) if len(s.strip()) > 35]
    if len(clean_content) >= 250 and len(sentences) < 2:
        return False, "Content lacks multiple narrative sentences required for an individual news article."
    elif len(sentences) < 1:
        return False, "Content lacks narrative reporting required for an individual news article."

    reporting_verbs = {"said", "reported", "announced", "agreed", "met", "signed", "launched", "stated", "confirmed", "told", "warned", "spoke", "convened", "declared", "negotiated", "condemned", "proposed"}
    has_reporting_verb = any(v in content_lower for v in reporting_verbs)

    named_actors = {
        "president", "minister", "prime minister", "secretary", "envoy", "ambassador", "official", "officials",
        "un", "united nations", "nato", "eu", "european union", "white house", "kremlin", "pentagon",
        "us", "united states", "russia", "ukraine", "china", "iran", "israel", "gaza", "lebanon", "taiwan",
        "zelensky", "araghchi", "biden", "blinken", "security council", "ai", "openai", "bots", "census", "sec"
    }
    has_actor = any(a in content_lower for a in named_actors)
    has_article_slug = bool(re.search(r"/(articles|article|live|\d{4}/\d{2})/|/news/articles/", clean_url))

    if not has_reporting_verb and not has_actor and not has_article_slug:
        return False, "Content lacks named actors, reporting verbs, or article path characteristic of news reporting."

    return True, "Content verified as an individual news article with concrete reporting."


def _is_valid_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False


import html as html_lib


def _clean_html_text(html: str, max_chars: int = 4000) -> tuple[str, str]:
    """Extract clean title and body text from HTML using BeautifulSoup or regex fallback."""
    title = "Web Article"
    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form", "svg"]):
            element.decompose()
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        text_blocks = []
        for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            t = tag.get_text(separator=" ", strip=True)
            if len(t) > 25:
                text_blocks.append(t)
        raw_text = "\n\n".join(text_blocks) or soup.get_text(separator=" ", strip=True)
    else:
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if title_match:
            title = html_lib.unescape(title_match.group(1).strip())
        
        # Strip script, style, nav, header, footer, aside, noscript, svg, form tags
        cleaned = re.sub(r"<(script|style|nav|header|footer|aside|noscript|svg|form)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        
        # Extract substantive paragraph and heading tags
        blocks = []
        for m in re.finditer(r"<(p|h1|h2|h3)[^>]*>(.*?)</\1>", cleaned, flags=re.DOTALL | re.IGNORECASE):
            raw_block = m.group(2)
            plain = re.sub(r"<[^>]+>", " ", raw_block)
            plain = html_lib.unescape(re.sub(r"\s+", " ", plain).strip())
            plain_lower = plain.lower()
            if (
                len(plain) > 25
                and not any(nav in plain_lower for nav in ["skip to content", "cookie settings", "privacy policy", "all rights reserved"])
                and not plain_lower.startswith("image source")
                and not plain_lower.startswith("image caption")
            ):
                blocks.append(plain)
        
        if blocks:
            raw_text = "\n\n".join(blocks)
        else:
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            raw_text = html_lib.unescape(cleaned)

    content = raw_text[:max_chars].strip()
    return title, content


def read_url(
    url: str,
    simulate_failure: bool = False,
    timeout: int = 8,
    max_chars: int = 4000,
) -> ToolResult:
    """Fetch URL and extract clean text content."""
    start_time = time.time()

    # 1. Deterministic Failure Injection
    if simulate_failure:
        duration_ms = int((time.time() - start_time) * 1000)
        return ToolResult(
            success=False,
            data={"url": url, "content": "", "article_level": False},
            error="Simulated HTTP 504 Gateway Timeout on URL reader for recovery demonstration",
            duration_ms=duration_ms,
        )

    # 2. URL sanity validation
    clean_url = (url or "").strip()
    if not clean_url or not _is_valid_http_url(clean_url):
        duration_ms = int((time.time() - start_time) * 1000)
        return ToolResult(
            success=False,
            data={"url": clean_url, "content": "", "article_level": False},
            error=f"Invalid or unsupported URL scheme: '{clean_url}'",
            duration_ms=duration_ms,
        )

    headers = {
        "User-Agent": "ResearchPilot/1.0 (+https://github.com/google/ai-studio-researchpilot) Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        html = ""
        status_code = 200

        if requests:
            resp = requests.get(clean_url, headers=headers, timeout=timeout, allow_redirects=True)
            status_code = resp.status_code
            if status_code != 200:
                duration_ms = int((time.time() - start_time) * 1000)
                return ToolResult(
                    success=False,
                    data={"url": clean_url, "status_code": status_code, "article_level": False},
                    error=f"HTTP request returned error code {status_code}",
                    duration_ms=duration_ms,
                )
            html = resp.text
        else:
            req = urllib.request.Request(clean_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.status
                if status_code != 200:
                    duration_ms = int((time.time() - start_time) * 1000)
                    return ToolResult(
                        success=False,
                        data={"url": clean_url, "status_code": status_code, "article_level": False},
                        error=f"HTTP request returned error code {status_code}",
                        duration_ms=duration_ms,
                    )
                html = response.read().decode("utf-8", errors="replace")

        title, content = _clean_html_text(html, max_chars)
        word_count = len(content.split())
        duration_ms = int((time.time() - start_time) * 1000)

        # Content length check
        if len(content) < MIN_CONTENT_LENGTH:
            return ToolResult(
                success=False,
                data={"url": clean_url, "title": title, "content": content, "word_count": word_count, "article_level": False},
                error=f"Extracted content too short ({len(content)} chars < minimum {MIN_CONTENT_LENGTH})",
                duration_ms=duration_ms,
            )

        # Verify article vs landing page
        is_art, art_reason = is_article_content(clean_url, title, content)

        return ToolResult(
            success=True,
            data={
                "url": clean_url,
                "title": title,
                "content": content,
                "word_count": word_count,
                "article_level": is_art,
                "classification_reason": art_reason,
            },
            error=None,
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        err_str = str(e)
        if "timed out" in err_str.lower() or "timeout" in err_str.lower():
            return ToolResult(
                success=False,
                data={"url": clean_url, "content": "", "article_level": False},
                error=f"Connection timed out after {timeout} seconds fetching {clean_url}",
                duration_ms=duration_ms,
            )
        return ToolResult(
            success=False,
            data={"url": clean_url, "content": "", "article_level": False},
            error=f"Network error accessing URL: {err_str}",
            duration_ms=duration_ms,
        )
