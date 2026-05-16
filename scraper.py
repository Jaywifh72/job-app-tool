"""
Job posting scraper module.
Fetches and extracts job description content from a given URL.
Uses requests + BeautifulSoup for simple HTML, falls back to Playwright for JS-heavy pages.
"""

import re
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common selectors for known job boards
JOB_BOARD_SELECTORS = [
    # Generic / common
    "article",
    '[class*="job-description"]',
    '[class*="jobdescription"]',
    '[class*="posting"]',
    '[class*="description"]',
    '[id*="job-description"]',
    '[id*="jobdescription"]',
    "main",
    # LinkedIn
    ".show-more-less-html",
    ".jobs-description__content",
    '[class*="jobs-description"]',
    # Indeed
    "#jobDescriptionText",
    '.jobsearch-jobDescriptionText',
    # Glassdoor
    ".jobDescriptionContent",
    '#JobDescriptionContainer',
    # Workday / Taleo
    '[data-automation-id*="jobDescription"]',
    '[data-automation-id*="jobPosting"]',
    # Greenhouse
    ".description",
    # Lever
    ".posting-description",
]


def scrape_job_posting(url: str, timeout: int = 30) -> str:
    """
    Scrape the job posting at the given URL and return the text content.

    First tries a simple requests + BeautifulSoup approach.
    If that yields insufficient content, falls back to Playwright.
    """
    logger.info(f"Scraping job posting: {url}")

    # Try simple fetch first
    content = _fetch_simple(url, timeout)
    if content and _has_substantial_content(content):
        logger.info("Simple fetch succeeded")
        return content

    # Try Playwright fallback
    logger.info("Simple fetch insufficient, trying Playwright...")
    content = _fetch_playwright(url, timeout)
    if content and _has_substantial_content(content):
        logger.info("Playwright fetch succeeded")
        return content

    if content:
        logger.warning("Some content extracted but may be incomplete")
        return content

    raise RuntimeError(f"Failed to scrape job posting from: {url}")


def _fetch_simple(url: str, timeout: int) -> str | None:
    """Fetch and parse page content using requests + BeautifulSoup."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # Try job board selectors first
        for selector in JOB_BOARD_SELECTORS:
            elements = soup.select(selector)
            if elements:
                # Return the longest match
                best = max(elements, key=lambda e: len(e.get_text(strip=True)))
                text = best.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    return text

        # Fallback: extract all visible text
        text = soup.get_text(separator="\n", strip=True)
        # Clean up whitespace
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)
        return text if len(text) > 100 else None

    except Exception as e:
        logger.warning(f"Simple fetch failed: {e}")
        return None


def _fetch_playwright(url: str, timeout: int) -> str | None:
    """Fetch page content using Playwright for JS-rendered pages."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            # Wait a beat for JS to render
            page.wait_for_timeout(2000)
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        for selector in JOB_BOARD_SELECTORS:
            elements = soup.select(selector)
            if elements:
                best = max(elements, key=lambda e: len(e.get_text(strip=True)))
                text = best.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    return text

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Playwright fetch failed: {e}")
        return None


def _has_substantial_content(text: str, min_words: int = 50) -> bool:
    """Check if the extracted text has enough content to be useful."""
    word_count = len(text.split())
    return word_count >= min_words


def summarize_job_posting(text: str, max_chars: int = 8000) -> str:
    """Truncate job posting text to fit within token limits."""
    if len(text) <= max_chars:
        return text
    # Try to cut at a sentence boundary
    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    last_newline = truncated.rfind("\n")
    cut = max(last_period, last_newline)
    if cut > max_chars // 2:
        return text[: cut + 1]
    return truncated + "\n\n[... content truncated ...]"
