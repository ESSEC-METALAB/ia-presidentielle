"""SourceReader for the Assemblée nationale's open-data verbatim record.

Each paragraph of the compte rendu names its speaker by actor id, so attribution is
exact rather than a surname match. One archive (~53 MB, every séance of the
legislature) serves every configured person: it is downloaded and parsed once per
process. Archive and séance URL shapes come from the previous version (branch
`daily`), where they were measured against the live service.
"""

import io
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from observatoire.adapters.sources.documents import make_document, on_or_after
from observatoire.adapters.sources.http_client import PoliteHttpClient
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source
from observatoire.domain.ports import Clock
from observatoire.services.dates import parse_date_prefix

_NS = "{http://schemas.assemblee-nationale.fr/referentiel}"
_SEANCE_URL = "https://www.assemblee-nationale.fr/dyn/{legislature}/comptes-rendus/seance/{uid}"


class _Options(BaseModel):
    acteur: str = Field(pattern=r"^PA\d+$")
    legislature: str = Field(pattern=r"^\d+$")


class _Seance(BaseModel):
    model_config = ConfigDict(frozen=True)

    uid: str
    held_on: date | None
    day_label: str
    speeches: dict[str, str]  # actor id -> everything that actor said in the séance


class AssembleeNationaleReader:
    """One document per séance in which the configured actor spoke."""

    def __init__(self, http: PoliteHttpClient, clock: Clock) -> None:
        self._http = http
        self._clock = clock
        self._archives: dict[str, tuple[_Seance, ...]] = {}

    def fetch(self, source: Source, since: date | None) -> Iterator[RawDocument]:
        options = _Options.model_validate(source.options)
        fetched_at = self._clock.now()
        for seance in self._seances(source.url):
            text = seance.speeches.get(options.acteur)
            if not text or not on_or_after(seance.held_on, since):
                continue
            yield make_document(
                source,
                url=_SEANCE_URL.format(legislature=options.legislature, uid=seance.uid),
                title=f"Séance du {seance.day_label}" if seance.day_label else seance.uid,
                text=text,
                published_on=seance.held_on,
                fetched_at=fetched_at,
            )

    def _seances(self, url: str) -> tuple[_Seance, ...]:
        if url not in self._archives:
            self._archives[url] = tuple(_parse_archive(self._http.get(url).content, url))
        return self._archives[url]


def _parse_archive(content: bytes, url: str) -> Iterator[_Seance]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise SourceUnavailableError(url, f"not a zip archive: {error}") from error
    with archive:
        for name in archive.namelist():
            seance = _parse_seance(archive.read(name)) if name.endswith(".xml") else None
            if seance is not None:
                yield seance


def _parse_seance(xml: bytes) -> _Seance | None:
    """A malformed séance is skipped, never guessed at."""
    try:
        # A single known publisher over HTTPS; expat refuses external entities and
        # bounds entity expansion, so defusedxml would add a dependency, not safety.
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    speeches = _speeches_by_actor(root)
    if not speeches:
        return None
    meta = root.find(f"{_NS}metadonnees")
    return _Seance(
        uid=root.findtext(f"{_NS}uid") or "",
        held_on=parse_date_prefix(meta.findtext(f"{_NS}dateSeance") if meta is not None else None),
        day_label=(meta.findtext(f"{_NS}dateSeanceJour") if meta is not None else None) or "",
        speeches=speeches,
    )


def _speeches_by_actor(root: ElementTree.Element) -> dict[str, str]:
    """Chairing the sitting ("la parole est à…") is procedure, not a position: dropped."""
    by_actor: dict[str, list[str]] = defaultdict(list)
    for paragraph in root.iter(f"{_NS}paragraphe"):
        actor = paragraph.get("id_acteur")
        if not actor or actor == "PA0" or paragraph.get("roledebat") == "president":
            continue
        node = paragraph.find(f"{_NS}texte")
        said = " ".join("".join(node.itertext()).split()) if node is not None else ""
        if said:
            by_actor[actor].append(said)
    return {actor: "\n\n".join(parts) for actor, parts in by_actor.items()}
