"""Build gold/speakers.csv: the production speaker rule run on ~26 broadcaster
videos, for a person to label by ear. Resumable: rows already written are skipped.

Run from the repository root, with a current yt-dlp on PATH:

    uv run python scripts/build_speaker_sheet.py

The pick (two videos per broadcaster channel, shortest and longest, plus four
where the candidate clearly speaks) is written once to
~/.cache/observatoire/speaker_pick.tsv; channels move, so a rerun from scratch
picks different videos. The sheet built on 2026-11-17 is gold/speakers.csv."""
import csv, collections, subprocess, sys, traceback
from pathlib import Path
import yaml
from observatoire import transcribe as T
from observatoire.fetch import match_people

out = Path("gold/speakers.csv")
cfg = yaml.safe_load(open("sources.yaml", encoding="utf-8"))
people = cfg["people"]
pick_file = Path.home() / ".cache/observatoire/speaker_pick.tsv"

if not pick_file.exists():
    per = collections.defaultdict(list)
    for src in (s for s in cfg["shared"] if s["type"] == "video"):
        r = subprocess.run(["yt-dlp", "--no-update", "--flat-playlist", "--playlist-end", "300",
                            "--extractor-args", "youtube:lang=fr", "--print",
                            "%(duration)s\t%(webpage_url)s\t%(title)s", src["url"]],
                           capture_output=True, text=True, timeout=300)
        for line in r.stdout.splitlines():
            dur, url, title = line.split("\t", 2)
            named = match_people(title, people)
            if len(named) == 1 and dur.replace(".", "").isdigit() and 180 <= float(dur) <= 2700:
                per[src["label"]].append((src["label"], float(dur), url, title, named[0]["slug"]))
    pick = []
    for ch, rs in sorted(per.items()):  # the shortest and the longest of each channel
        rs.sort(key=lambda r: r[1])
        pick += [rs[0]] + ([rs[-1]] if len(rs) > 1 else [])
    pick = pick[:22] + [  # four where the candidate clearly speaks
        ("BFMTV", 4029, "https://www.youtube.com/watch?v=LbbnPYMFngU", "\"Je n'ai qu'une chose raisonnable à vous proposer, il faut tout changer\", déclare Jean-Luc Mélenchon", "jean-luc-melenchon"),
        ("TF1 Info", 522, "https://www.youtube.com/watch?v=kPfm-5IgI9w", "Jordan Bardella est l'invité du 20H de TF1 avec Gilles Bouleau｜TF1 INFO", "jordan-bardella"),
        ("TF1 Info", 918, "https://www.youtube.com/watch?v=1xFor4Zkbu8", "Présidentielle 2027 - \"Route nationale\" avec Gabriel Attal dans LE20H｜TF1 INFO", "gabriel-attal"),
        ("Télématin", 651, "https://www.youtube.com/watch?v=-jkkqOVt3q0", "Les 4 vérités - Gabriel Attal - Émission du vendredi 23 octobre 2026", "gabriel-attal")]
    pick_file.write_text("".join("\t".join(map(str, r)) + "\n" for r in pick), encoding="utf-8")
    print("picked", len(pick), flush=True)

fields = ["n", "channel", "minutes", "candidate", "title", "url", "rule", "top_voice_share",
          "check_1", "heard_1", "check_2", "heard_2", "check_3", "heard_3",
          "LABEL_voice_is_candidate", "LABEL_candidate_speaks_much", "notes"]
done = {r["url"] for r in csv.DictReader(out.open(encoding="utf-8"))} if out.exists() else set()
new = not out.exists()
with out.open("a", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    if new:
        w.writeheader()
    for n, line in enumerate(pick_file.read_text(encoding="utf-8").splitlines(), 1):
        channel, dur, url, title, person = line.split("\t")
        if url in done:
            continue
        try:
            said = T.turns(T.audio(url), T.Path.home() / ".cache/observatoire/models")
            talk = collections.Counter()
            for t in said:
                talk[t.speaker] += t.end - t.start
            top, secs = talk.most_common(1)[0]
            row = {"rule": "attributes" if T.dominant_speaker(said) is not None else "abstains",
                   "top_voice_share": f"{secs / sum(talk.values()):.0%}"}
            own = [t for t in said if t.speaker == top]
            for i, f in enumerate((0.2, 0.5, 0.8), 1):
                t = own[int(len(own) * f)]
                s = int(t.start)
                row[f"check_{i}"] = f"{url}&t={s}s ({s // 60}:{s % 60:02d})"
                row[f"heard_{i}"] = t.text[:120]
        except Exception as e:
            traceback.print_exc()
            row = {"rule": f"ERROR {type(e).__name__}", "notes": str(e)[:200]}
        w.writerow({"n": n, "channel": channel, "minutes": round(float(dur) / 60),
                    "candidate": person, "title": title, "url": url, **row})
        fh.flush()
        print(n, row["rule"], row.get("top_voice_share"), title[:60], flush=True)
print("DONE", flush=True)
