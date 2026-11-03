"""Writes the public register site: the template files, plus the generated data script."""

import shutil
from pathlib import Path

DATA_SCRIPT = "data.js"


def write_site(template_dir: Path, out_dir: Path, data_script: str) -> Path:
    """Copies `template_dir` into `out_dir`, then writes `data.js`. Returns the page."""
    shutil.copytree(template_dir, out_dir, dirs_exist_ok=True)
    (out_dir / DATA_SCRIPT).write_text(data_script, encoding="utf-8")
    return out_dir / "index.html"
