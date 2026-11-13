"""Video leads → documents: audio, speaker turns, and a rule for whose turns
they are.

Auto-captions carry no speaker labels, so a multi-speaker video stops at a
lead (see ``fetch.fetch_video``). This stage takes those leads further:
download the audio, split it into speaker turns, transcribe each turn, and —
when a rule can say which voice is the candidate the title names — keep that
voice's turns as a document. Everything else stays a lead.

**No model names anyone.** Speaker separation clusters voices into anonymous
speakers 0, 1, 2. The name comes from the title (a deterministic match against
``sources.yaml``) and the choice of voice from talk time. That keeps the rule
that the model never reports provenance.

The models are local, small, pinned by hash, and chosen on the command line,
so a better one is a new row in a table rather than new code.
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
import sherpa_onnx

from .fetch import _ytdlp, captions, match_people
from .schema import Cue, Document, Lead, Tier
from .store import Store
from .transcript import flatten, mentions_ai

SAMPLE_RATE = 16_000  # what every model below was trained on
# Whisper reads at most 30 seconds at a time; a turn longer than this is cut.
WHISPER_WINDOW_S = 28.0

# Placeholder, unmeasured. The dominant voice of a video whose title names
# exactly one candidate is taken to be that candidate. It is wrong whenever a
# title names who is *discussed* rather than who *speaks*: a commentator's
# analysis, a report with voice-over, a party colleague praising the leader.
# It must be scored against hand-labelled videos before it feeds the daily
# review. Until then every claim it yields is tier-unconfirmed (the asterisk).
DOMINANT_SHARE = 0.5


@dataclass(frozen=True)
class Model:
    url: str
    sha256: str

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[1].removesuffix(".tar.bz2")


_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# Pinned by hash: a model is part of how a quote was heard, so changing one is a
# reviewed change, not a URL that moved. To try a larger Whisper, add its row;
# the files inside every sherpa-onnx Whisper archive follow the same naming.
ASR = {
    "tiny": Model(f"{_RELEASES}/asr-models/sherpa-onnx-whisper-tiny.tar.bz2",
                  "c46116994e539aa165266d96b325252728429c12535eb9d8b6a2b10f129e66b1"),
}
SEGMENTATION = Model(
    f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488")
EMBEDDING = Model(
    f"{_RELEASES}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx",
    "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94")


def fetch_model(model: Model, cache: Path) -> Path:
    """Downloaded once, checked against its pin, unpacked if an archive.

    Unpacked beside the cache and renamed into place, so a crash halfway
    leaves no half-written model for the next run to load.
    """
    target = cache / model.name
    if target.exists():
        return target
    cache.mkdir(parents=True, exist_ok=True)
    r = httpx.get(model.url, follow_redirects=True, timeout=600)
    r.raise_for_status()
    digest = hashlib.sha256(r.content).hexdigest()
    if digest != model.sha256:
        raise RuntimeError(f"{model.name}: sha256 {digest}, pinned {model.sha256}")
    with tempfile.TemporaryDirectory(dir=cache) as tmp:
        if model.url.endswith(".tar.bz2"):
            with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:bz2") as tar:
                tar.extractall(tmp, filter="data")
            (Path(tmp) / model.name).rename(target)
        else:
            (Path(tmp) / model.name).write_bytes(r.content)
            (Path(tmp) / model.name).rename(target)
    return target


def audio(url: str) -> np.ndarray:
    """The video's sound as 16 kHz mono samples."""
    with tempfile.TemporaryDirectory() as tmp:
        _ytdlp(["-f", "bestaudio", "-o", f"{tmp}/audio.%(ext)s", url])
        src = next(Path(tmp).iterdir())
        # S603/S607: ffmpeg from PATH, reading a file this function just wrote.
        pcm = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error",  # noqa: S603, S607
                              "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE),
                              "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.float32)


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: int
    text: str


def turns(samples: np.ndarray, cache: Path, asr: str = "tiny") -> list[Turn]:
    """Who spoke when, then what they said, one piece at a time."""
    threads = os.cpu_count() or 1
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(fetch_model(SEGMENTATION, cache) / "model.onnx")),
            num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(fetch_model(EMBEDDING, cache)), num_threads=threads),
        # -1: the number of speakers is not known in advance.
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1)))
    segments = diarizer.process(samples).sort_by_start_time()

    w = fetch_model(ASR[asr], cache)
    recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=str(w / f"{asr}-encoder.int8.onnx"), decoder=str(w / f"{asr}-decoder.int8.onnx"),
        tokens=str(w / f"{asr}-tokens.txt"), language="fr", num_threads=threads)
    pieces = []
    for seg in segments:
        start = seg.start
        while start < seg.end:
            end = min(start + WHISPER_WINDOW_S, seg.end)
            pieces.append((start, end, seg.speaker))
            start = end
    streams = []
    for start, end, _ in pieces:
        stream = recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE,
                               samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)])
        streams.append(stream)
    recognizer.decode_streams(streams)
    return [Turn(start, end, speaker, s.result.text.strip())
            for (start, end, speaker), s in zip(pieces, streams, strict=True)
            if s.result.text.strip()]


def dominant_speaker(said: list[Turn]) -> int | None:
    """The voice holding more than ``DOMINANT_SHARE`` of the talk time, if any."""
    talk: Counter[int] = Counter()
    for t in said:
        talk[t.speaker] += t.end - t.start
    if not talk:
        return None
    speaker, seconds = talk.most_common(1)[0]
    return speaker if seconds / sum(talk.values()) > DOMINANT_SHARE else None


def to_document(lead: Lead, said: list[Turn], speaker: int) -> Document:
    own = [t for t in said if t.speaker == speaker]
    return Document(
        person=lead.person, source_id=lead.source_id, kind="video",
        # Whose words, not who hosts: the candidate's own speech is tier 1
        # wherever it is broadcast. Unconfirmed, because a rule named the
        # speaker, not a record — the editor confirms by ear at the timestamp.
        tier=Tier.OWN_WORDS, tier_confirmed=False,
        url=lead.url, title=lead.title, date=lead.date,
        text=" ".join(t.text for t in own),
        cues=[Cue(t=int(t.start), line=t.text) for t in own],
    )


@dataclass
class Report:
    examined: int = 0
    promoted: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    errors: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"video leads examined {self.examined} · promoted to documents {self.promoted}"]
        lines += [f"  {n:>4} {why}" for why, n in self.skipped.most_common()]
        lines += [f"  ERR {url}: {err}" for url, err in self.errors.items()]
        return "\n".join(lines)


def run(store: Store, people: list[dict], cache: Path, asr: str = "tiny") -> Report:
    """Promote the video leads the rule can attribute. Each lead is examined
    once per ASR model, so a better model re-examines everything."""
    report = Report()
    for lead in store.leads():
        done = f"{lead.url_hash}:transcribed:{asr}"
        if ":video:" not in lead.source_id or not store.is_new(done):
            continue
        report.examined += 1
        try:
            why = _examine(lead, people, store, cache, asr)
        except Exception as e:  # one video must not stop the others
            report.errors[lead.url] = f"{type(e).__name__}: {e}"[:300]
            continue  # not marked done: tomorrow tries again
        if why:
            report.skipped[why] += 1
        else:
            report.promoted += 1
        store.mark_seen(done, lead.url)
        store.commit()
    return report


def _examine(lead: Lead, people: list[dict], store: Store, cache: Path, asr: str) -> str | None:
    """``None`` if the lead became a document, otherwise why not."""
    if [p["slug"] for p in match_people(lead.title, people)] != [lead.person]:
        return "title does not name exactly one candidate"
    # Free before paid: captions cost one request, audio costs minutes of compute.
    cues = captions(lead.url)
    if cues is not None and not mentions_ai(flatten(cues)):
        return "captions do not mention AI"
    said = turns(audio(lead.url), cache, asr)
    speaker = dominant_speaker(said)
    if speaker is None:
        return "no dominant voice"
    doc = to_document(lead, said, speaker)
    if not mentions_ai(doc.text):
        return "the dominant voice does not mention AI"
    store.add_document(doc)
    return None


if __name__ == "__main__":
    import argparse

    import yaml

    ap = argparse.ArgumentParser(
        description="Turn video leads into documents: audio → speaker turns → "
                    "the named candidate's own turns.")
    ap.add_argument("--db", default="data/observatoire.db")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--asr", default="tiny", choices=sorted(ASR),
                    help="Whisper size; larger is slower and hears better")
    ap.add_argument("--models", type=Path,
                    default=Path.home() / ".cache" / "observatoire" / "models",
                    help="where downloaded models are kept between runs")
    args = ap.parse_args()

    people = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8"))["people"]
    store = Store(args.db)
    report = run(store, people, args.models, args.asr)
    store.close()
    print(report.summary())
    raise SystemExit(1 if report.errors else 0)
