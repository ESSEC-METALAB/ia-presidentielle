#!/usr/bin/env bash
# Packs the built register (data/site) into dist/registre-ia-2027-hors-ligne.zip: the site
# plus double-click launchers (packaging/offline/) that serve it on the reader's own
# computer with what the system already ships (python3 or perl, PowerShell on Windows).
# The reader installs nothing and needs no internet.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f data/site/index.html ]]; then
    echo "Pas de site à empaqueter : lancez d'abord « make site » (ou « make register »)." >&2
    exit 1
fi
mkdir -p dist
python3 -I - data/site packaging/offline dist/registre-ia-2027-hors-ligne.zip <<'PY'
import sys
import zipfile
from pathlib import Path

site, launchers, archive = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
TOP = "registre-ia-2027"
EXECUTABLE = 0o100755 << 16
REGULAR = 0o100644 << 16
# Where each launcher file goes in the archive, and whether it must be executable.
LAYOUT = {
    "Ouvrir le registre (Mac).command": ("", True),
    "Ouvrir le registre (Windows).bat": ("", False),
    "ouvrir-le-registre-linux.sh": ("", True),
    "LISEZ-MOI.txt": ("", False),
    "lancer.sh": ("outils/", True),
    "serveur.pl": ("outils/", True),
    "serveur.ps1": ("outils/", False),
}


def add(bundle: zipfile.ZipFile, source: Path, name: str, executable: bool) -> None:
    info = zipfile.ZipInfo(f"{TOP}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
    info.external_attr = EXECUTABLE if executable else REGULAR
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix, so the permission bits above are honoured on unzip
    bundle.writestr(info, source.read_bytes())


with zipfile.ZipFile(archive, "w") as bundle:
    for file_name, (folder, executable) in LAYOUT.items():
        add(bundle, launchers / file_name, folder + file_name, executable)
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        add(bundle, path, "site/" + path.relative_to(site).as_posix(), False)
print(f"{archive} ({archive.stat().st_size // 1024} Ko)")
PY
