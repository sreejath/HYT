#!/usr/bin/env python3
"""Export a Skilljar course or learning path into a single Markdown file.

Skilljar lessons are gated behind a learner login, and many of them are SCORM
packages (Articulate Rise/Storyline and friends) that only exist as rendered
DOM inside an iframe.  So this drives a real browser: you sign in once, the
session is saved, and every lesson is loaded, scrolled to force lazy content
in, and flattened to Markdown.

Usage
-----
    # first run - sign in through the browser window that opens, then press Enter
    python skilljar_export.py --login <path-, course- or lesson-URL>

    # later runs reuse the saved session
    python skilljar_export.py <path-, course- or lesson-URL>

Output (under --out, default ./out)
-----------------------------------
    <slug>.md        the consolidated file - this is the thing you want
    lessons/*.md     one file per lesson, doubles as the resume cache
    raw/             per-lesson raw HTML plus captured JS/JSON/XML/VTT payloads
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

try:
    from bs4 import BeautifulSoup
    from markdownify import markdownify as html2md
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright
except ImportError as exc:  # pragma: no cover - dependency guard
    sys.exit(
        f"missing dependency: {exc.name}\n"
        "  pip install -r requirements.txt && playwright install chromium"
    )


# --------------------------------------------------------------------------
# URL shapes
#
# Skilljar lesson URLs always end in /<lesson-id>/<lesson-type>/<slug>, whether
# the course sits inside a learning path or stands alone:
#   /path/<path-slug>/<course-slug>/486636/scorm/2dk4fzu1k4lj
#   /<course-slug>/486636/html/abc123
# Everything before those last three segments is the course URL.
# --------------------------------------------------------------------------
LESSON_RE = re.compile(r"^(?P<course>/.+?)/(?P<lid>\d+)/(?P<ltype>[a-z0-9_]+)/(?P<slug>[^/]+)$")
PATH_COURSE_RE = re.compile(r"^/path/[^/]+/[^/]+$")
PATH_ROOT_RE = re.compile(r"^(/path/[^/]+)")

CONTENT_SELECTORS = [
    "#skilljar-content", ".skilljar-content",
    "#lesson-content", ".lesson-content",
    "#curriculum-content", ".curriculum-content",
    "main", "#content", "article", ".content-wrapper",
]
STRIP_SELECTORS = [
    "script", "style", "noscript", "svg", "nav", "header", "footer",
    "#skilljar-navigation", ".skilljar-nav", ".skilljar-header", ".skilljar-footer",
    ".lesson-nav", ".course-nav", ".navbar", "#sidebar", ".sidebar",
    ".breadcrumb", ".breadcrumbs", ".cookie-banner", "[role=navigation]",
]
TEXTUAL_TYPES = ("json", "javascript", "ecmascript", "xml", "text/vtt", "text/plain")
MAX_RAW_BYTES = 2 * 1024 * 1024
MAX_RAW_FILES = 40

SCROLL_JS = """
async () => {
  const el = document.scrollingElement || document.documentElement;
  let previous = -1;
  for (let i = 0; i < 60; i++) {
    el.scrollTop = el.scrollHeight;
    await new Promise(r => setTimeout(r, 250));
    if (el.scrollHeight === previous) break;
    previous = el.scrollHeight;
  }
  el.scrollTop = 0;
}
"""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def normalize(url: str) -> str:
    """Drop query/fragment and any trailing slash so URLs dedupe cleanly."""
    parts = urlparse(url)
    path = parts.path.rstrip("/") or "/"
    return urlunparse((parts.scheme, parts.netloc, path, "", "", ""))


def slugify(text: str, fallback: str = "untitled") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or fallback


def demote_headings(markdown: str, levels: int = 3) -> str:
    """Push lesson headings below the ones this exporter emits.

    Fence-aware, because a prompting course is full of code and prompt blocks
    where a leading '#' is a comment, not a heading.
    """
    out, in_fence = [], False
    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        m = re.match(r"^(#{1,6})(\s+)(.*)$", line) if not in_fence else None
        if m:
            depth = min(len(m.group(1)) + levels, 6)
            out.append("#" * depth + m.group(2) + m.group(3))
        else:
            out.append(line)
    return "\n".join(out)


def tidy(markdown: str) -> str:
    markdown = re.sub(r"[ \t]+$", "", markdown, flags=re.M)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


def html_to_markdown(html: str, base_url: str | None = None, whole_page: bool = False) -> str:
    """Flatten a page (or iframe document) to Markdown, chrome removed."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in STRIP_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    root = None
    if not whole_page:
        for selector in CONTENT_SELECTORS:
            el = soup.select_one(selector)
            if el and el.get_text(strip=True):
                root = el
                break
    if root is None:
        root = soup.body or soup

    if base_url:
        for a in root.find_all("a", href=True):
            a["href"] = urljoin(base_url, a["href"])
        for img in root.find_all("img", src=True):
            img["src"] = urljoin(base_url, img["src"])

    return tidy(html2md(str(root), heading_style="ATX"))


def strip_leading_title(markdown: str, title: str) -> str:
    """Drop a leading heading that only repeats the lesson title."""
    lines = markdown.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        m = re.match(r"^#{1,6}\s+(.*)$", lines[i])
        if m and m.group(1).strip().lower() == title.strip().lower():
            return "\n".join(lines[i + 1:]).strip()
    return markdown


def merge_parts(parts: list[str]) -> str:
    """Join page + iframe extractions, dropping ones already covered.

    A SCORM lesson usually yields near-identical text from the wrapper page and
    the package frame; keeping both doubles the file for no gain. The longer
    extraction wins whenever one contains the other.
    """
    kept: list[str] = []
    for part in (p.strip() for p in parts):
        if not part:
            continue
        if any(part in k for k in kept):
            continue                       # already covered by something longer
        kept = [k for k in kept if k not in part]   # this one supersedes those
        kept.append(part)
    return tidy("\n\n".join(kept))


def looks_like_login(page_url: str, markdown: str) -> bool:
    if re.search(r"/(auth|login|sign-?in|accounts?)(/|$)", urlparse(page_url).path):
        return True
    head = markdown[:400].lower()
    return "sign in" in head and "password" in head


# --------------------------------------------------------------------------
# exporter
# --------------------------------------------------------------------------
class Exporter:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.seed = normalize(args.url)
        parts = urlparse(self.seed)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.host = parts.netloc

        self.out = Path(args.out)
        self.lessons_dir = self.out / "lessons"
        self.raw_dir = self.out / "raw"
        self.state_file = Path(args.auth_state)

        self.course_titles: dict[str, str] = {}
        self.warnings: list[str] = []

    # -- auth ------------------------------------------------------------
    async def ensure_auth(self, pw) -> None:
        if self.state_file.exists() and not self.args.login:
            return
        print("Opening a browser window. Sign in to Skilljar, navigate to the "
              "course so you know the session works, then come back here.")
        browser = await pw.chromium.launch(headless=False, executable_path=self.args.browser_path)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(self.origin, wait_until="load")
        await asyncio.get_running_loop().run_in_executor(
            None, input, "Press Enter once you are signed in... "
        )
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(self.state_file))
        await browser.close()
        print(f"Session saved to {self.state_file}")

    # -- page loading ----------------------------------------------------
    async def load(self, page, url: str, capture: list | None = None) -> str:
        """Navigate, settle, scroll everything, return the main document HTML."""
        handler = None
        if capture is not None:
            def handler(response):  # noqa: ANN001 - playwright callback
                ctype = (response.headers or {}).get("content-type", "")
                if any(t in ctype for t in TEXTUAL_TYPES):
                    capture.append(response.url)
            page.on("response", handler)

        last_error: Exception | None = None
        for attempt in range(self.args.retries + 1):
            try:
                await page.goto(url, wait_until="load", timeout=self.args.timeout * 1000)
                break
            except PlaywrightError as exc:
                last_error = exc
                if attempt == self.args.retries:
                    if handler:
                        page.remove_listener("response", handler)
                    raise
                await page.wait_for_timeout(1500 * (attempt + 1))
        del last_error

        await page.wait_for_timeout(self.args.settle)
        for frame in page.frames:
            try:
                await frame.evaluate(SCROLL_JS)
            except PlaywrightError:
                pass
        await page.wait_for_timeout(self.args.settle)

        html = await page.content()
        if handler:
            page.remove_listener("response", handler)
        return html

    async def frame_markdown(self, page) -> list[str]:
        """Markdown for every child frame - this is where SCORM content lives."""
        chunks = []
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            try:
                html = await frame.content()
            except PlaywrightError:
                continue
            md = html_to_markdown(html, base_url=frame.url, whole_page=True)
            if len(md) > 40:
                chunks.append(md)
        return chunks

    # -- discovery -------------------------------------------------------
    async def links(self, page) -> list[str]:
        hrefs = await page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        )
        seen, ordered = set(), []
        for href in hrefs:
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            url = normalize(urljoin(page.url, href))
            if urlparse(url).netloc != self.host or url in seen:
                continue
            seen.add(url)
            ordered.append(url)
        return ordered

    def lesson_course(self, url: str) -> str | None:
        m = LESSON_RE.match(urlparse(url).path)
        return f"{self.origin}{m.group('course')}" if m else None

    async def discover(self, page) -> list[tuple[str, list[str]]]:
        """Return [(course_url, [lesson_url, ...]), ...] in course order."""
        path_match = PATH_ROOT_RE.match(urlparse(self.seed).path)
        seed_course = self.lesson_course(self.seed)

        course_urls: list[str] = []
        if path_match and not self.args.course_only:
            path_url = f"{self.origin}{path_match.group(1)}"
            print(f"reading learning path {path_url}")
            await self.load(page, path_url)
            self.course_titles[path_url] = await self.page_title(page)
            for url in await self.links(page):
                if PATH_COURSE_RE.match(urlparse(url).path) and url not in course_urls:
                    course_urls.append(url)
            self.root_title = self.course_titles.get(path_url, "Skilljar export")
        else:
            self.root_title = ""

        if seed_course and seed_course not in course_urls:
            course_urls.insert(0, seed_course)
        if not course_urls:
            course_urls = [normalize(self.seed)]

        results: list[tuple[str, list[str]]] = []
        for course_url in course_urls:
            print(f"reading course {course_url}")
            try:
                await self.load(page, course_url)
            except PlaywrightError as exc:
                self.warnings.append(f"could not open course {course_url}: {exc}")
                continue
            self.course_titles[course_url] = await self.page_title(page)
            lessons = [u for u in await self.links(page) if self.lesson_course(u) == course_url]

            # Course landing pages are sometimes thin; a lesson page always
            # carries the full sidebar TOC, so fall back to that.
            if not lessons:
                probe = self.seed if seed_course == course_url else None
                if probe:
                    await self.load(page, probe)
                    lessons = [u for u in await self.links(page)
                               if self.lesson_course(u) == course_url]
            if lessons:
                results.append((course_url, lessons))
            else:
                self.warnings.append(f"no lessons found under {course_url}")
        return results

    async def page_title(self, page) -> str:
        for selector in ("h1", ".skilljar-title", ".course-title", "title"):
            try:
                el = await page.query_selector(selector)
                if el:
                    text = (await el.inner_text()).strip() if selector != "title" else \
                           (await page.title()).strip()
                    if text:
                        return re.sub(r"\s+", " ", text)
            except PlaywrightError:
                continue
        return "Untitled"

    # -- raw capture -----------------------------------------------------
    async def save_raw(self, context, folder: Path, page_html: str, urls: list[str]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "page.html").write_text(page_html, encoding="utf-8")
        for i, url in enumerate(list(dict.fromkeys(urls))[:MAX_RAW_FILES]):
            try:
                response = await context.request.get(url, timeout=self.args.timeout * 1000)
                body = await response.body()
            except PlaywrightError:
                continue
            if len(body) > MAX_RAW_BYTES:
                continue
            name = slugify(Path(urlparse(url).path).name or f"asset{i}", f"asset{i}")
            suffix = Path(urlparse(url).path).suffix[:6] or ".txt"
            (folder / f"{i:02d}-{name}{suffix}").write_bytes(body)

    # -- lessons ---------------------------------------------------------
    async def export_lesson(self, context, page, index: int, url: str) -> dict:
        m = LESSON_RE.match(urlparse(url).path)
        ltype = m.group("ltype") if m else "lesson"

        cache = self.lessons_dir / f"{index:03d}-{slugify(urlparse(url).path.split('/')[-1])}.md"
        if cache.exists() and not self.args.force:
            body = cache.read_text(encoding="utf-8")
            title = body.split("\n", 1)[0].lstrip("# ").strip()
            print(f"  [{index:03d}] cached  {title}")
            return {"url": url, "title": title, "type": ltype,
                    "markdown": body.split("\n", 1)[-1].strip()}

        capture: list[str] = []
        html = await self.load(page, url, capture=capture if not self.args.no_raw else None)
        title = await self.page_title(page)

        parts = [html_to_markdown(html, base_url=url)]
        parts.extend(await self.frame_markdown(page))
        markdown = merge_parts([strip_leading_title(p, title) for p in parts])

        if looks_like_login(page.url, markdown):
            raise RuntimeError(
                "hit a login page - the saved session has expired. "
                "Re-run with --login."
            )
        if len(markdown) < 60:
            note = f"little or no text extracted for {url}"
            self.warnings.append(note)
            markdown = f"_[{note} - check out/raw/ for the raw payloads]_"

        if not self.args.no_raw:
            await self.save_raw(context, self.raw_dir / f"{index:03d}", html, capture)

        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(f"# {title}\n\n{markdown}\n", encoding="utf-8")
        print(f"  [{index:03d}] {ltype:<8} {title}  ({len(markdown)} chars)")
        return {"url": url, "title": title, "type": ltype, "markdown": markdown}

    # -- assembly --------------------------------------------------------
    def doc_title(self, courses: list[tuple[str, list[dict]]]) -> str:
        """Path title when exporting a whole path, else the single course's."""
        if self.root_title:
            return self.root_title
        if courses:
            return self.course_titles.get(courses[0][0], "Skilljar export")
        return "Skilljar export"

    def assemble(self, courses: list[tuple[str, list[dict]]]) -> str:
        title = self.doc_title(courses)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        doc = [f"# {title}", "",
               f"Source: <{self.seed}>  ", f"Exported: {stamp}", "", "## Contents", ""]

        for course_url, lessons in courses:
            cname = self.course_titles.get(course_url, course_url)
            doc.append(f"- **{cname}**")
            for lesson in lessons:
                doc.append(f"  - [{lesson['title']}](#{slugify(lesson['title'])})")
        doc.append("")

        for course_url, lessons in courses:
            cname = self.course_titles.get(course_url, course_url)
            doc += ["", "---", "", f"## {cname}", "", f"<{course_url}>", ""]
            for lesson in lessons:
                doc += [f"### {lesson['title']}", "",
                        f"`{lesson.get('type', 'lesson')}` · <{lesson['url']}>", "",
                        demote_headings(lesson["markdown"]), ""]

        if self.warnings:
            doc += ["", "---", "", "## Export warnings", ""]
            doc += [f"- {w}" for w in self.warnings]
        return "\n".join(doc).rstrip() + "\n"

    # -- driver ----------------------------------------------------------
    async def run(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        self.lessons_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            await self.ensure_auth(pw)
            browser = await pw.chromium.launch(
                headless=not self.args.headed, executable_path=self.args.browser_path
            )
            context = await browser.new_context(
                storage_state=str(self.state_file) if self.state_file.exists() else None
            )
            page = await context.new_page()

            try:
                discovered = await self.discover(page)
                if not discovered:
                    print("No lessons discovered. Check the URL, or re-run with "
                          "--login if the session expired.", file=sys.stderr)
                    return 1

                total = sum(len(v) for _, v in discovered)
                print(f"found {total} lessons across {len(discovered)} course(s)")

                index, courses = 0, []
                for course_url, lesson_urls in discovered:
                    exported = []
                    for lesson_url in lesson_urls:
                        index += 1
                        try:
                            exported.append(await self.export_lesson(context, page, index, lesson_url))
                        except RuntimeError:
                            raise
                        except Exception as exc:  # noqa: BLE001 - one bad lesson must not kill the run
                            self.warnings.append(f"failed on {lesson_url}: {exc}")
                            print(f"  [{index:03d}] FAILED  {lesson_url}: {exc}", file=sys.stderr)
                        await page.wait_for_timeout(self.args.delay)
                    courses.append((course_url, exported))
            finally:
                await browser.close()

        target = self.out / f"{slugify(self.doc_title(courses), 'skilljar-course')}.md"
        target.write_text(self.assemble(courses), encoding="utf-8")
        print(f"\nwrote {target} ({target.stat().st_size:,} bytes)")
        if self.warnings:
            print(f"{len(self.warnings)} warning(s) - see the end of the file")
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", help="a Skilljar path, course or lesson URL")
    p.add_argument("--login", action="store_true", help="force an interactive sign-in first")
    p.add_argument("--auth-state", default="skilljar-auth.json", help="saved session file")
    p.add_argument("--out", default="out", help="output directory (default: out)")
    p.add_argument("--course-only", action="store_true",
                   help="export just the seed course, not every course in the path")
    p.add_argument("--force", action="store_true", help="ignore the per-lesson cache")
    p.add_argument("--no-raw", action="store_true", help="skip raw HTML/asset capture")
    p.add_argument("--headed", action="store_true", help="watch the crawl in a visible browser")
    p.add_argument("--browser-path", default=None, help="explicit Chromium executable")
    p.add_argument("--delay", type=int, default=750, help="ms between lessons (default: 750)")
    p.add_argument("--settle", type=int, default=1500,
                   help="ms to wait for JS/SCORM content to render (default: 1500)")
    p.add_argument("--timeout", type=int, default=60, help="per-navigation timeout in seconds")
    p.add_argument("--retries", type=int, default=2, help="navigation retries per lesson")
    args = p.parse_args()

    try:
        return asyncio.run(Exporter(args).run())
    except KeyboardInterrupt:
        print("\ninterrupted - already-exported lessons are cached, re-run to resume")
        return 130
    except RuntimeError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
