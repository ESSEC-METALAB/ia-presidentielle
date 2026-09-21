"""Fetch every configured source and normalise it.

Two outputs, never one:

``documents``  tier 1-2 full text → will become claims
``leads``      tier 3, paywalled, or multi-speaker video → a question for the
               editor, never an auto-published claim

That split is not only policy. Press bodies are largely unreachable: Google
News links redirect to a consent wall, and paywalled French majors return a
teaser (Le Monde: *"Il vous reste 60.87% de cet article à lire"*). Quoting the
teaser under *courte citation* is the lawful route, and it needs a human.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date as Date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
import pymupdf
import trafilatura
import yaml
from trafilatura.sitemaps import sitemap_search

from .schema import Cue, Document, Lead, Tier
from .store import Store
from .transcript import flatten, mentions_ai, parse_vtt

UA = "ESSECMetalabBot/1.0 (+https://metalab.essec.edu)"

# trafilatura defaults to extensive_search, which *guesses* a date when the page
# carries none, and the guess has the shape 1 January of whichever year it found.
# A date is part of the evidence, so an invented one is worse than none at all.
NO_DATE_GUESSING = {"date_extraction_params": {"extensive_search": False}}
MIN_INTERVAL = 1.0  # seconds between requests to the same host

_robots: dict[str, RobotFileParser | None] = {}
_last_hit: dict[str, float] = {}


# --------------------------------------------------------------------------
# Politeness. An institutional crawler that gets blocked embarrasses the
# institute, so identify yourself, obey robots.txt, and space out requests.
# --------------------------------------------------------------------------


def _host(url: str) -> str:
    return urlparse(url).netloc


def allowed(url: str) -> bool:
    host = _host(url)
    if host not in _robots:
        rp = RobotFileParser()
        rp.set_url(f"{urlparse(url).scheme}://{host}/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None  # unreachable robots.txt is not a prohibition
        _robots[host] = rp
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(UA, url)


def _throttle(url: str) -> None:
    host = _host(url)
    wait = MIN_INTERVAL - (time.monotonic() - _last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def get(url: str, timeout: float = 30.0) -> httpx.Response | None:
    if not allowed(url):
        return None
    _throttle(url)
    try:
        r = httpx.get(url, follow_redirects=True, timeout=timeout, headers={"User-Agent": UA})
        return r if r.status_code == 200 else None
    except Exception:
        return None


SNAPSHOT = re.compile(r"web\.archive\.org/web/\d{14}/")


def archive(url: str, timeout: float = 25.0) -> str | None:
    """Best-effort Wayback snapshot, taken at ingest so a citation survives the
    page being edited or deleted.

    Two steps, because save-page-now is asynchronous. Requesting a save does not
    return the snapshot URL, so we ask for one and then resolve what exists via
    the dated-redirect form. A real snapshot redirects to a 14-digit timestamp
    path. No snapshot returns the query URL unchanged, or a "not archived" page
    served with HTTP 200 — which is why the caller must check the shape and not
    merely that a string came back.

    Returns ``None`` on failure, and the archive lint then refuses to publish a
    claim with no receipt. That is the correct outcome.
    """
    headers = {"User-Agent": UA}
    try:  # ask for a fresh capture; do not wait for it to finish
        httpx.get(f"https://web.archive.org/save/{url}", follow_redirects=True,
                  timeout=timeout, headers=headers)
    except Exception:
        pass
    try:  # resolve whatever snapshot now exists
        r = httpx.get(f"https://web.archive.org/web/2/{url}", follow_redirects=True,
                      timeout=timeout, headers=headers)
    except Exception:
        return None
    final = str(r.url)
    return final if r.status_code == 200 and SNAPSHOT.search(final) else None


def _parse_date(value: str | None) -> Date | None:
    if not value:
        return None
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", value.strip())
    if not m:
        return None
    try:
        return Date(*(int(g) for g in m.groups()))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Fetchers. Each returns (documents, leads); most return one empty list.
# --------------------------------------------------------------------------

Result = tuple[list[Document], list[Lead]]


def fetch_rss(src: dict, person: dict, sid: str) -> Result:
    feed = feedparser.parse(src["url"])
    docs: list[Document] = []
    for entry in feed.entries[: src.get("max", 20)]:
        link = entry.get("link")
        if not link:
            continue
        r = get(link)
        if r is None:
            continue
        extracted = trafilatura.extract(r.text, output_format="json", with_metadata=True,
                                     **NO_DATE_GUESSING)
        if not extracted:
            continue
        meta = json.loads(extracted)
        text = (meta.get("text") or "").strip()
        if len(text) < 400:  # a teaser, not an article
            continue
        docs.append(Document(
            person=person["slug"], source_id=sid, kind="rss", tier=Tier(str(src["tier"])),
            url=link, text=text, title=meta.get("title"),
            date=_parse_date(meta.get("date")) or _parse_date(entry.get("published")),
            fingerprint=meta.get("fingerprint"),
        ))
    return docs, []


def fetch_pdf(src: dict, person: dict, sid: str) -> Result:
    r = get(src["url"], timeout=60)
    if r is None:
        return [], []
    with pymupdf.open(stream=r.content, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    if not text.strip():
        return [], []
    return [Document(
        person=person["slug"], source_id=sid, kind="pdf", tier=Tier(str(src["tier"])),
        url=src["url"], text=text.strip(), title=src.get("label"),
        date=_parse_date(src.get("date")),
    )], []


def fetch_site(src: dict, person: dict, sid: str) -> Result:
    """Exhaustive crawl of one chosen domain, via its sitemap.

    Measured on republicains.fr: 251 URLs, 4.3 minutes, zero robots refusals,
    **14 AI-bearing pages against 1 from the same site's RSS** — including
    Retailleau's Station F speech, which falls outside the 15-item feed window.

    This is a *backfill*, not a daily source. Published archives do not change,
    so it runs once per domain and RSS carries the delta thereafter. Re-crawling
    hundreds of unchanged pages every morning would be wasteful and impolite.

    The AI prefilter applies here for the same reason it applies to video: a
    bulk crawl is an order of magnitude more pages than a normal run, and a
    French political page discussing AI without a single term from the list
    does not exist.
    """
    try:
        urls = sitemap_search(src["url"], target_lang="fr")
    except Exception:
        return [], []
    docs: list[Document] = []
    for u in urls[: src.get("max", 500)]:
        r = get(u, timeout=30)
        if r is None:
            continue
        extracted = trafilatura.extract(r.text, output_format="json", with_metadata=True,
                                     **NO_DATE_GUESSING)
        if not extracted:
            continue
        meta = json.loads(extracted)
        text = (meta.get("text") or "").strip()
        if len(text) < 400 or not mentions_ai(text):
            continue
        docs.append(Document(
            person=person["slug"], source_id=sid, kind="site", tier=Tier(str(src["tier"])),
            url=u, text=text, title=meta.get("title"),
            date=_parse_date(meta.get("date")), fingerprint=meta.get("fingerprint"),
        ))
    return docs, []


def fetch_page(src: dict, person: dict, sid: str) -> Result:
    """One standing URL, re-read each run. Candidates publish priorities pages
    with no feed; those are their own words, so tier 1."""
    r = get(src["url"], timeout=45)
    if r is None:
        return [], []
    extracted = trafilatura.extract(r.text, output_format="json", with_metadata=True,
                                     **NO_DATE_GUESSING)
    if not extracted:
        return [], []
    meta = json.loads(extracted)
    text = (meta.get("text") or "").strip()
    if len(text) < 400:
        return [], []
    return [Document(
        person=person["slug"], source_id=sid, kind="page", tier=Tier(str(src["tier"])),
        url=src["url"], text=text, title=src.get("label") or meta.get("title"),
        date=_parse_date(meta.get("date")), fingerprint=meta.get("fingerprint"),
    )], []


def _ytdlp(args: list[str]) -> str:
    """Raises on failure rather than returning empty output.

    Returning ``out.stdout`` regardless of the exit code made the two
    outcomes that matter indistinguishable: a video whose transcript carries
    no AI content produces nothing, and a blocked yt-dlp also produces
    nothing — ``fetch_youtube`` would ``continue`` past both. Measured
    2026-09-21: from a GitHub runner, caption download fails with *"Sign in to
    confirm you're not a bot"* while the playlist listing still succeeds, so
    the silent version would have reported a healthy source forever.

    ``fetch.run`` already records a per-source exception without stopping the
    morning, so raising here surfaces the problem instead of burying it.
    """
    out = subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"yt-dlp exited {out.returncode}: {out.stderr.strip()[:300]}")
    return out.stdout


def fetch_youtube(src: dict, person: dict, sid: str) -> Result:
    """``speakers: single`` becomes documents; ``multi`` becomes leads.

    Auto-captions carry no speaker labels, so on an interview a question from
    the journalist is indistinguishable from the candidate's answer. The
    quote-in-source lint cannot catch that — the quote really is in the
    transcript, it is simply not his.
    """
    single = src.get("speakers") == "single"
    listing = _ytdlp(["--flat-playlist", "--print", "%(id)s\t%(title)s\t%(upload_date)s",
                      "--playlist-end", str(src.get("max", 10)), src["channel"]])
    docs: list[Document] = []
    leads: list[Lead] = []
    for line in filter(None, listing.splitlines()):
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        vid, title, upload = parts[0], parts[1], (parts[2] if len(parts) > 2 else "")
        url = f"https://youtu.be/{vid}"
        if not single:
            leads.append(Lead(person=person["slug"], source_id=sid, title=title, url=url,
                              publisher=src.get("label"), date=_parse_date(upload),
                              reason="multi-speaker video: no speaker labels in captions"))
            continue
        with tempfile.TemporaryDirectory() as tmp:
            _ytdlp(["--skip-download", "--write-auto-subs", "--sub-lang", "fr",
                    "--sub-format", "vtt", "-o", f"{tmp}/%(id)s.%(ext)s", url])
            vtt = next(Path(tmp).glob("*.vtt"), None)
            if vtt is None:
                continue
            cues = parse_vtt(vtt.read_text(encoding="utf-8", errors="replace"))
        text = flatten(cues)
        if not mentions_ai(text):  # a 90-min transcript is ~29K tokens; check first
            continue
        docs.append(Document(
            person=person["slug"], source_id=sid, kind="youtube", tier=Tier(str(src["tier"])),
            url=url, text=text, title=title, date=_parse_date(upload),
            cues=[Cue(t=t, line=l) for t, l in cues],
        ))
    return docs, leads


def fetch_news(src: dict, person: dict, sid: str) -> Result:
    """Discovery only. Bodies are unreachable behind consent walls, so this
    produces leads: *"X wrote about this on the 15th — do we have it from a
    primary source?"*
    """
    feed = feedparser.parse(src["url"])
    leads = [
        Lead(person=person["slug"], source_id=sid, title=e.get("title", "(untitled)"),
             url=e["link"], publisher=(e.get("source") or {}).get("title"),
             date=_parse_date(e.get("published")), reason="press: body behind consent wall")
        for e in feed.entries[: src.get("max", 20)] if e.get("link")
    ]
    return [], leads


# --------------------------------------------------------------------------
# Assemblée nationale — comptes rendus intégraux
#
# The official verbatim record, and the first source that does not have to
# guess whose words it carries: every paragraph names its speaker by a stable
# actor id, so attribution is exact rather than a surname match. It is also
# the first source whose tier is confirmed by the record itself.
#
# One archive serves every configured person, so it is parsed once per run and
# each person reads their own paragraphs out of it.
# --------------------------------------------------------------------------

AN_NS = "{http://schemas.assemblee-nationale.fr/referentiel}"
AN_ARCHIVE = ("https://data.assemblee-nationale.fr/static/openData/repository/"
              "{legislature}/vp/syceronbrut/syseron.xml.zip")
AN_SEANCE = "https://www.assemblee-nationale.fr/dyn/{legislature}/comptes-rendus/seance/{uid}"


def _an_paragraphs(root) -> dict[str, str]:
    """Speaker id → everything that speaker said in this séance.

    ``roledebat="president"`` is dropped: chairing the sitting produces "la
    parole est à M. X", which is procedure, not a position. It matters because
    a candidate can preside.
    """
    by_speaker: dict[str, list[str]] = {}
    for para in root.iter(f"{AN_NS}paragraphe"):
        acteur = para.get("id_acteur")
        if not acteur or acteur == "PA0" or para.get("roledebat") == "president":
            continue
        node = para.find(f"{AN_NS}texte")
        if node is None:
            continue
        said = " ".join("".join(node.itertext()).split())
        if said:
            by_speaker.setdefault(acteur, []).append(said)
    return {k: "\n\n".join(v) for k, v in by_speaker.items()}


@lru_cache(maxsize=1)
def _an_seances(url: str) -> tuple:
    """Download and parse the whole archive, once.

    ~53 MB and 600 séances, regenerated daily. Cached for the process because
    four configured people would otherwise download and parse it four times.
    """
    raw = httpx.get(url, timeout=300, follow_redirects=True)
    raw.raise_for_status()
    out = []
    with zipfile.ZipFile(io.BytesIO(raw.content)) as archive:
        for name in archive.namelist():
            if not name.endswith(".xml"):
                continue
            try:
                root = ET.fromstring(archive.read(name))
            except ET.ParseError:
                continue  # a malformed séance is skipped, never guessed at
            said = _an_paragraphs(root)
            if not said:
                continue
            meta = root.find(f"{AN_NS}metadonnees")
            out.append((
                root.findtext(f"{AN_NS}uid") or "",
                _parse_date(meta.findtext(f"{AN_NS}dateSeance") if meta is not None else None),
                (meta.findtext(f"{AN_NS}dateSeanceJour") if meta is not None else None) or "",
                said,
            ))
    return tuple(out)


def fetch_an(src: dict, person: dict, sid: str) -> Result:
    """One document per séance in which this person actually spoke."""
    acteur = src["acteur"]
    legislature = str(src.get("legislature", 17))
    since = _parse_date(src.get("since"))
    docs = []
    for uid, date, jour, said in _an_seances(AN_ARCHIVE.format(legislature=legislature)):
        text = said.get(acteur)
        if not text or (since and date and date < since):
            continue
        docs.append(Document(
            person=person["slug"], source_id=sid, kind="an",
            tier=Tier(str(src["tier"])),
            # Confirmed, not defaulted: the record names the speaker, so no
            # editor has to decide whose words these are.
            tier_confirmed=True,
            url=AN_SEANCE.format(legislature=legislature, uid=uid),
            text=text, title=f"Séance du {jour}" if jour else uid, date=date,
        ))
    return docs, []


def fetch_x(src: dict, person: dict, sid: str) -> Result:
    raise NotImplementedError(
        "X fetcher is pending Phase 0 spike 3: needs an API key and a measured "
        "posts/day figure before the endpoint shape is committed to code."
    )


FETCHERS = {"rss": fetch_rss, "pdf": fetch_pdf, "page": fetch_page, "site": fetch_site,
            "youtube": fetch_youtube, "news": fetch_news, "x": fetch_x, "an": fetch_an}

# Archive crawls are one-off. Daily runs skip them; --backfill includes them.
BACKFILL_ONLY = {"site"}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def to_lead(doc: Document, reason: str) -> Lead:
    """Demote a fetched document to a lead, dropping its body."""
    return Lead(person=doc.person, source_id=doc.source_id,
                title=doc.title or "(untitled)", url=doc.url,
                date=doc.date, reason=reason)


def route(docs: list[Document], leads: list[Lead]) -> tuple[list[Document], list[Lead]]:
    """Tier decides, centrally — not inside each fetcher.

    Tier 3 is press reporting *about* someone, so it can never be a claim
    however cleanly the body extracted. The body is still fetched, because it
    is what name-matching runs against, but only the headline survives.
    """
    kept, demoted = [], list(leads)
    for doc in docs:
        if doc.tier == Tier.PRESS:
            demoted.append(to_lead(doc, "press: reporting, not the person's own words"))
        else:
            kept.append(doc)
    return kept, demoted


def match_people(text: str, people: list[dict]) -> list[dict]:
    """Which configured people are named in this text.

    Shared feeds (tech press) cover everyone, so attribution has to happen
    somewhere. It happens here, by deterministic name match — never by asking
    the model, which must not be trusted to report provenance.
    """
    low = text.lower()
    return [p for p in people
            if any(re.search(rf"\b{re.escape(m.lower())}\b", low) for m in p.get("match", []))]


def source_id(person: dict, src: dict) -> str:
    key = src.get("url") or src.get("channel") or src.get("query") or ""
    return f"{person['slug']}:{src['type']}:{hashlib.sha1(key.encode()).hexdigest()[:8]}"


@dataclass
class RunReport:
    documents: int = 0
    leads: int = 0
    skipped_duplicates: int = 0
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # (fetched, kept)
    errors: dict[str, str] = field(default_factory=dict)
    dead: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"documents {self.documents} · leads {self.leads} · "
                 f"duplicates skipped {self.skipped_duplicates}"]
        for sid, (fetched, kept) in sorted(self.counts.items()):
            flag = "  ⚠ source returned nothing" if fetched == 0 else ""
            lines.append(f"  {kept:>4} kept / {fetched:<3} fetched  {sid}{flag}")
        for sid, err in sorted(self.errors.items()):
            lines.append(f"  ERR   {sid}: {err}")
        if self.dead:
            lines.append(f"\nDEAD (no items in 3 consecutive runs): {', '.join(self.dead)}")
        return "\n".join(lines)


def run(sources_path: str | Path, store: Store, *, do_archive: bool = True,
        only: str | None = None, backfill: bool = False) -> RunReport:
    config = yaml.safe_load(Path(sources_path).read_text(encoding="utf-8"))
    people = config["people"]
    report = RunReport()

    # Shared feeds are fetched once, then attributed to whichever configured
    # people they actually name. An item naming nobody is dropped.
    for src in config.get("shared", []):
        if not src.get("enabled", True):
            continue
        if (src["type"] in BACKFILL_ONLY) != backfill:
            continue  # same gate as per-person sources
        sid = f"shared:{src['type']}:{hashlib.sha1(src.get('url','').encode()).hexdigest()[:8]}"
        fetcher = FETCHERS.get(src["type"])
        if fetcher is None:
            report.errors[sid] = f"unknown source type {src['type']!r}"
            continue
        probe = {"slug": "_shared"}
        try:
            docs, leads = fetcher(src, probe, sid)
        except Exception as e:
            report.errors[sid] = f"{type(e).__name__}: {e}"
            report.counts[sid] = (0, 0)
            store.record_run(sid, 0, 0)
            continue

        docs, leads = route(docs, leads)
        kept = 0
        for item in [*docs, *leads]:
            haystack = getattr(item, "text", None) or item.title or ""
            for person in match_people(f"{item.title or ''} {haystack}", people):
                scoped = item.model_copy(update={"person": person["slug"]})
                if not store.is_new(scoped.url_hash + person["slug"]):
                    report.skipped_duplicates += 1
                    continue
                store.mark_seen(scoped.url_hash + person["slug"], scoped.url)
                if isinstance(scoped, Lead):
                    store.add_lead(scoped)
                    report.leads += 1
                else:
                    if do_archive:
                        scoped.archive_url = archive(scoped.url)
                    store.add_document(scoped)
                    report.documents += 1
                kept += 1
        report.counts[sid] = (len(docs) + len(leads), kept)
        store.record_run(sid, len(docs) + len(leads), kept)
        store.commit()

    for person in people:
        if only and person["slug"] != only:
            continue
        for src in person.get("sources", []):
            sid = source_id(person, src)
            fetcher = FETCHERS.get(src["type"])
            if fetcher is None:
                report.errors[sid] = f"unknown source type {src['type']!r}"
                continue
            if not src.get("enabled", True):
                continue
            if (src["type"] in BACKFILL_ONLY) != backfill:
                continue  # archive crawls only on --backfill; everything else only without
            try:
                docs, leads = fetcher(src, person, sid)
            except NotImplementedError as e:
                report.errors[sid] = str(e).split(":")[0]
                continue
            except Exception as e:  # one broken source must not stop the morning
                report.errors[sid] = f"{type(e).__name__}: {e}"
                report.counts[sid] = (0, 0)
                store.record_run(sid, 0, 0)
                continue

            docs, leads = route(docs, leads)
            kept = 0
            for doc in docs:
                if not store.is_new(doc.url_hash):
                    report.skipped_duplicates += 1
                    continue
                if do_archive:
                    doc.archive_url = archive(doc.url)
                store.add_document(doc)
                kept += 1
                report.documents += 1
            for lead in leads:
                if not store.is_new(lead.url_hash):
                    report.skipped_duplicates += 1
                    continue
                store.add_lead(lead)
                kept += 1
                report.leads += 1

            report.counts[sid] = (len(docs) + len(leads), kept)
            store.record_run(sid, len(docs) + len(leads), kept)
            # Commit per source, not once at the end: an archive backfill runs
            # for minutes, and a crash partway should not discard the work.
            store.commit()

    store.commit()
    report.dead = store.dead_sources()
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Fetch all configured sources.")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--db", default="data/observatoire.db")
    ap.add_argument("--no-archive", action="store_true", help="skip Wayback (much faster)")
    ap.add_argument("--only", help="restrict to one person slug")
    ap.add_argument("--backfill", action="store_true",
                    help="run archive crawls (site sources) instead of the daily sources")
    args = ap.parse_args()

    store = Store(args.db)
    report = run(args.sources, store, do_archive=not args.no_archive, only=args.only,
                 backfill=args.backfill)
    print(report.summary())
    store.close()
    raise SystemExit(1 if report.dead else 0)
