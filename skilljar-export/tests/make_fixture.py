#!/usr/bin/env python3
"""Build a static site that mimics Skilljar's URL shapes and page structure.

Lets the exporter be smoke-tested end to end without touching the real site:
a learning path, two courses, plain + SCORM-in-an-iframe lessons, and a lazily
rendered block that only appears once the frame is scrolled.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "fixture_site")


def write(rel: str, html: str) -> None:
    target = ROOT / rel / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "<!doctype html><html><head><title>Fixture</title></head><body>"
        '<nav class="skilljar-nav"><a href="/">catalog chrome that must be stripped</a></nav>'
        f"{html}"
        '<footer>footer chrome that must be stripped</footer>'
        "</body></html>",
        encoding="utf-8",
    )


P = "/path/claude-certified-associate-foundations"
C1 = f"{P}/prompting-task-execution"
C2 = f"{P}/context-and-tools"

if ROOT.exists():
    shutil.rmtree(ROOT)

# learning path -> courses
write(P.lstrip("/"), f"""
  <h1>Claude Certified Associate: Foundations</h1>
  <main>
    <ul>
      <li><a href="{C1}">Prompting &amp; Task Execution</a></li>
      <li><a href="{C2}">Context and Tools</a></li>
      <li><a href="/catalog">Unrelated catalog link</a></li>
    </ul>
  </main>
""")

# course 1 -> lessons
write(C1.lstrip("/"), f"""
  <h1>Prompting &amp; Task Execution</h1>
  <main><ol>
    <li><a href="{C1}/486635/html/intro01">Prompt anatomy</a></li>
    <li><a href="{C1}/486636/scorm/2dk4fzu1k4lj">Task execution patterns</a></li>
  </ol></main>
""")

write(f"{C1.lstrip('/')}/486635/html/intro01", """
  <h1>Prompt anatomy</h1>
  <div class="skilljar-content">
    <h2>The four parts</h2>
    <p>A workable prompt states the <strong>role</strong>, the task, the
       constraints, and the output shape.</p>
    <ul><li>Role</li><li>Task</li><li>Constraints</li><li>Format</li></ul>
    <pre><code># not a heading, a comment
You are a research assistant.
Summarise the document in five bullets.</code></pre>
    <p>See <a href="/glossary">the glossary</a>.</p>
  </div>
""")

# course 1, lesson 2 -> SCORM package in an iframe
write(f"{C1.lstrip('/')}/486636/scorm/2dk4fzu1k4lj", """
  <h1>Task execution patterns</h1>
  <div class="skilljar-content">
    <iframe src="/scorm/pkg-2dk4/" width="100%" height="600"></iframe>
  </div>
""")

# course 2 -> one lesson
write(C2.lstrip("/"), f"""
  <h1>Context and Tools</h1>
  <main><ol>
    <li><a href="{C2}/486640/html/ctx01">Context windows</a></li>
  </ol></main>
""")

write(f"{C2.lstrip('/')}/486640/html/ctx01", """
  <h1>Context windows</h1>
  <div class="skilljar-content">
    <p>Context is the working memory of a single request.</p>
    <h3>Budgeting</h3>
    <p>Put durable instructions first and volatile data last.</p>
  </div>
""")

# the "SCORM package": content below the fold only renders after scrolling
(ROOT / "scorm/pkg-2dk4").mkdir(parents=True, exist_ok=True)
(ROOT / "scorm/pkg-2dk4/index.html").write_text("""<!doctype html>
<html><head><title>SCORM package</title></head><body>
  <h1>Task execution patterns</h1>
  <p>Decomposition beats one giant instruction.</p>
  <div style="height:2000px"></div>
  <div id="lazy"></div>
  <script src="/scorm/pkg-2dk4/data.js"></script>
  <script>
    addEventListener('scroll', () => {
      if (window.scrollY > 300 && !document.getElementById('lazy').innerHTML) {
        document.getElementById('lazy').innerHTML =
          '<h2>Verification</h2><p>Always close the loop: run the check that ' +
          'proves the task actually succeeded.</p>';
      }
    });
  </script>
</body></html>""", encoding="utf-8")

(ROOT / "scorm/pkg-2dk4/data.js").write_text(
    'window.courseData = {"slides":[{"notes":"Raw payload the exporter should capture."}]};\n',
    encoding="utf-8",
)

print(f"fixture written to {ROOT.resolve()}")
