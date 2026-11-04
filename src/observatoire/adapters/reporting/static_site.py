"""Writes the public register site: the template files, plus the generated data script.

The page asks for `data.js` and `refresh.js` with their content hash in the URL
(`data.js?v=…`). A CDN in front of the site may keep scripts in browsers for hours
whatever the server says (Cloudflare's browser cache TTL did, on 2026-11-04): the page
itself is never cached, so a new hash makes browsers fetch the new data at once.
"""

import hashlib
import re
import shutil
from pathlib import Path

DATA_SCRIPT = "data.js"
_VERSIONED = (DATA_SCRIPT, "refresh.js")


def write_site(template_dir: Path, out_dir: Path, data_script: str) -> Path:
    """Copies `template_dir` into `out_dir`, then writes `data.js`. Returns the page."""
    shutil.copytree(template_dir, out_dir, dirs_exist_ok=True)
    (out_dir / DATA_SCRIPT).write_text(data_script, encoding="utf-8")
    page = out_dir / "index.html"
    if page.exists():
        page.write_text(_versioned(page.read_text(encoding="utf-8"), out_dir), encoding="utf-8")
    return page


def _versioned(html: str, site: Path) -> str:
    for name in _VERSIONED:
        script = site / name
        if not script.exists():
            continue
        digest = hashlib.sha256(script.read_bytes()).hexdigest()[:12]
        pattern = re.compile(r"""(src=["']\./""" + re.escape(name) + r""")(["'])""")
        html = pattern.sub(rf"\g<1>?v={digest}\g<2>", html)
    return html
