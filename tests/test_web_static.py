"""Silent failure caught: anything that would break the strict CSP (inline script, inline style
attribute, on* handler, a remote asset) or turn model text into markup (innerHTML and friends),
plus a referenced asset that is missing, or a font shipped without its licence. A green page in
dev would otherwise be blank behind the production Content-Security-Policy.
Stdlib plus pytest only.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
GITHUB = "https://github.com/KiritoH4Z3/ask-hana"
HTML_FILES = sorted(WEB.glob("*.html"))


class Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline_scripts, self.style_attrs, self.handlers, self.urls = [], [], [], []
        self._script_src = None
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k, v in attrs:
            if k == "style":
                self.style_attrs.append(tag)
            if k.startswith("on"):
                self.handlers.append((tag, k))
            if k in ("src", "href") and v:
                self.urls.append((tag, k, v))
        if tag == "script":
            self._in_script = not a.get("src")
        if tag == "style":
            self.style_attrs.append("<style> element")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.inline_scripts.append(data.strip()[:40])


def scan(path):
    s = Scan()
    s.feed(path.read_text(encoding="utf-8"))
    return s


def test_html_files_exist():
    assert HTML_FILES, "web/index.html missing, an empty tree must not pass"


def test_no_inline_script_bodies():
    for f in HTML_FILES:
        assert not scan(f).inline_scripts, f.name


def test_no_style_attributes_or_style_elements():
    for f in HTML_FILES:
        assert not scan(f).style_attrs, f.name


def test_no_on_handler_attributes():
    for f in HTML_FILES:
        assert not scan(f).handlers, f.name


def test_no_remote_urls_except_the_github_link():
    for f in HTML_FILES:
        for tag, k, v in scan(f).urls:
            if re.match(r"(?i)(https?:)?//", v):
                assert v == GITHUB, f"{f.name}: remote {tag} {k}={v}"


def test_every_local_asset_exists():
    for f in HTML_FILES:
        for _tag, _k, v in scan(f).urls:
            if re.match(r"(?i)(https?:|mailto:|#|data:)", v) or v.startswith("//"):
                continue
            assert not v.startswith("/"), f"{f.name}: absolute asset URL {v}"
            assert (WEB / v.split("#")[0].split("?")[0]).exists(), f"{f.name}: missing {v}"


def test_css_urls_are_relative_and_exist():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\(\s*[\"']?([^)\"']+)", css)
    assert urls, "fonts should be referenced"
    for u in urls:
        assert not re.match(r"(?i)(https?:|//|/)", u), u
        assert (WEB / u).exists(), f"missing {u}"


def test_app_js_has_no_html_injection_sinks():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert len(js) > 500
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert sink not in js, sink


def test_scripts_are_external_and_local():
    for f in HTML_FILES:
        srcs = [v for tag, k, v in scan(f).urls if tag == "script"]
        assert "app.js" in srcs
        assert all(not v.startswith("http") for v in srcs)


def test_every_font_family_has_a_licence_file():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    fam = set(re.findall(r"font-family:\s*\"([^\"]+)\"\s*;\s*src", css))
    assert fam >= {"Bricolage Grotesque", "Hanken Grotesk", "IBM Plex Mono"}, fam
    licences = {
        p.name.lower(): p.read_text(encoding="utf-8", errors="ignore")
        for p in (WEB / "fonts").glob("OFL*.txt")
    }
    for family in fam:
        slug = family.lower().replace(" ", "-")
        match = [t for n, t in licences.items() if slug in n]
        assert match, f"no OFL file for {family}"
        assert "SIL OPEN FONT LICENSE" in match[0].upper()


def test_banned_fonts_are_not_used():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    for bad in ("Inter", "Roboto", "Arial", "Open Sans", "Fraunces", "Instrument Serif"):
        assert not re.search(rf"[\"',:\s]{bad}[\"',;\s]", css), bad


def test_no_em_dash_or_spaced_en_dash_in_web_files():
    for p in list(WEB.glob("*.html")) + [WEB / "app.js", WEB / "styles.css"]:
        t = p.read_text(encoding="utf-8")
        assert "—" not in t, p.name
        assert " – " not in t, p.name


# ---------------------------------------------------------------- ask flow (runs app.js in node)

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402


def _ask_flow() -> dict[str, dict]:
    node = shutil.which("node")
    if not node:
        pytest.fail("node is needed to run web/app.js against a fake DOM (tests/js/ask_flow.js)")
    out = subprocess.run(
        [node, str(WEB.parent / "tests" / "js" / "ask_flow.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    return {r["name"]: r for r in rows}


def test_failed_request_never_overwrites_what_the_visitor_typed_meanwhile():
    """Silent failure: the textarea stays editable while an answer loads, and a failed request
    replaced the follow-up the visitor was typing with the old question."""
    flow = _ask_flow()
    assert flow["server_error_keeps_new_draft"]["box"] == "a follow up I am typing"
    assert flow["server_error_restores_empty_box"]["box"] == "What is her cat called?"


def test_a_render_exception_is_not_reported_as_an_unreachable_server():
    """Silent failure: an exception while drawing a reply fell into the network catch, which
    printed 'Can't reach the server' and flipped the badge although the server had answered."""
    flow = _ask_flow()
    row = flow["render_error_is_not_unreachable"]
    assert "reach the server" not in row["log"] and "Server not reachable" not in row["badge"]
    assert "went wrong on the server" in row["log"]
    net = flow["network_failure_is_unreachable"]
    assert "reach the server" in net["log"] and net["badge"] == "Server not reachable"
