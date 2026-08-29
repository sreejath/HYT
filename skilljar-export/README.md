# skilljar-export

Exports a Skilljar course or learning path into **one Markdown file** — built for
studying a course offline (e.g. prepping for a certification exam) rather than
clicking through lessons one at a time.

It drives a real browser, because two things make plain HTTP scraping fail on
Skilljar:

- lessons are behind a learner login, and
- many lessons are SCORM packages (Articulate Rise/Storyline and similar) whose
  text only exists as rendered DOM inside an iframe, often lazily as you scroll.

So the script signs in once, saves the session, then loads each lesson, scrolls
the page **and every iframe** to force lazy content in, and flattens the result
to Markdown.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Use

```bash
# first run — a browser window opens; sign in, then press Enter in the terminal
python skilljar_export.py --login \
  "https://anthropic-partners.skilljar.com/path/claude-certified-associate-foundations/prompting-task-execution/486636/scorm/2dk4fzu1k4lj"

# later runs reuse the saved session
python skilljar_export.py "<same URL>"
```

Give it a **path**, **course**, or **lesson** URL. From a lesson URL inside a
learning path it walks up to the path and exports every course in it; pass
`--course-only` to stay inside the one course.

## Output

```
out/
  claude-certified-associate-foundations.md   <- the consolidated file
  lessons/001-....md                          <- one file per lesson (resume cache)
  raw/001/page.html, 00-data-js.js, ...       <- raw HTML + captured JS/JSON/XML/VTT
```

The consolidated file has a table of contents, then `## Course` / `### Lesson`
sections in course order, each with its source URL and lesson type. Headings
inside lesson content are demoted so they nest correctly, and code/prompt blocks
are left alone.

Interrupted runs resume: already-exported lessons come from `lessons/`. Use
`--force` to re-fetch.

## Options

| flag | purpose |
|---|---|
| `--login` | force an interactive sign-in (use when the session expires) |
| `--course-only` | export just the seed course, not the whole path |
| `--force` | ignore the per-lesson cache |
| `--headed` | watch the crawl in a visible browser |
| `--no-raw` | skip the `raw/` capture |
| `--settle N` | ms to wait for SCORM/JS to render (default 1500 — **raise this first** if lessons come out thin) |
| `--delay N` | ms between lessons (default 750) |
| `--browser-path` | explicit Chromium binary |
| `--out`, `--auth-state`, `--timeout`, `--retries` | as named |

## If a lesson comes out empty

Lessons with little or no extracted text are marked inline in the Markdown and
listed under **Export warnings** at the end of the file. In order:

1. Raise `--settle` (SCORM packages can be slow) and re-run with `--force`.
2. Run `--headed` to watch what actually renders.
3. Check `out/raw/<nnn>/` — slide-based Storyline courses often keep their text
   in a captured `.js`/`.xml` payload even when the DOM only shows one slide.

Slide-based SCORM that requires clicking **Next** through every slide is the
known hard case: scrolling won't reveal those slides, so the `raw/` payloads are
the fallback.

## Testing

```bash
./tests/smoke_test.sh
```

Builds a local fixture site that mimics Skilljar's URL shapes (path → courses →
lessons, plus a SCORM lesson with lazily-rendered iframe content), runs a full
export against it, and asserts on the result — discovery, ordering, iframe and
lazy-content extraction, chrome stripping, link absolutisation, code-fence
safety, and raw capture.

**What that does and doesn't prove:** the crawl, extraction and assembly logic
is verified end to end. The CSS selectors used to find lesson content on the
real site are best-effort, with fallbacks down to `<body>`; they were written
against Skilljar's conventions but could not be checked against
`anthropic-partners.skilljar.com` itself. If content lands in the file but
carries page furniture, adjust `CONTENT_SELECTORS` / `STRIP_SELECTORS` at the
top of the script.

## Note

Intended for personal offline study of a course you're enrolled in. Course
material is licensed to enrolled learners — don't redistribute the output.
