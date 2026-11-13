"""The extraction prompt. Versioned deliberately: its hash is recorded with
every batch, because a prompt change is as much a cause of a changed claim as
a model change is.
"""

from __future__ import annotations

import hashlib

AXES = {
    "regulation": "Regulating AI: the EU AI Act, national rules, bans, oversight bodies, "
                  "liability, or an explicit deregulation stance.",
    "souverainete": "Sovereignty and infrastructure: sovereign cloud, data localisation, "
                    "compute capacity, dependence on foreign providers, European preference. "
                    "Energy or compute presented as a national asset or industrial advantage "
                    "belongs here, not under environnement.",
    "environnement": "The environmental cost and resource demand of AI: electricity and water "
                     "consumption of data centres, waste-heat recovery, siting and land use, "
                     "carbon footprint; and AI applied to the ecological transition. Energy "
                     "framed as a sovereignty or industrial advantage is souverainete, not this.",
    "emploi": "Work: jobs created or displaced by AI, automation of tasks, labour law and "
              "working conditions, hiring, protection for exposed occupations. A labour-market "
              "measure belongs here even when it mentions skills.",
    "formation": "Education and training: schools, universities and higher education, the "
                 "engineer and researcher pipeline, AI literacy, continuing professional "
                 "training and reconversion. A measure delivered as teaching or training "
                 "belongs here even when its stated purpose is protecting jobs.",
    "services-publics": "AI inside the state: administration, public services, healthcare, "
                        "fraud detection, civil service headcount.",
    "surveillance-libertes": "Surveillance and civil liberties: facial recognition, policing, "
                             "algorithmic decisions about people, privacy. This is AI turned on "
                             "the population at home and what it does to their rights; defending "
                             "systems or the country from attack is securite or defense.",
    "securite": "Security: cybersecurity and the protection of critical infrastructure and "
                "systems, and foreign interference, disinformation or election manipulation. "
                "Protecting the country from an adversary by civilian means. AI used on the "
                "population at home is surveillance-libertes; who owns or controls the "
                "infrastructure is souverainete, while defending it from attack is here; the "
                "armed forces are defense.",
    "defense": "Defence: AI in the armed forces, military doctrine, autonomous weapons, drones "
               "and military cyber operations. Protecting civilian systems and infrastructure "
               "is securite.",
    "peur": "Fear: the risks of AI as a technology: loss of human control, catastrophic or "
            "existential risk, calls to pause or slow its development, AI safety research and "
            "institutes. The danger the person says AI itself poses. A concrete rule or "
            "oversight body is regulation; an attack by an adversary is securite or defense; "
            "jobs lost to AI are emploi.",
    "financement": "Money: public or private investment, tax measures, procurement, budgets.",
}

SYSTEM = """You extract stated positions on artificial-intelligence policy from French political documents, for a research publication of the ESSEC Metalab Institute.

You are given one document and the name of one person. Return every AI-policy position **that person states in this document**, and nothing else.

## Returning nothing is the correct answer most of the time

Most documents contain no AI-policy position at all. When that is the case, return an empty list. Do not stretch a passing mention of technology, data or modernisation into a policy position. Do not infer a position the person has not stated. An empty list is a successful extraction.

## The quote is the evidence and must be exact

`quote_fr` must be copied **character for character** from the document, in French. Do not paraphrase, translate, correct spelling, expand abbreviations, fix punctuation, or join separated fragments. It is checked against the source automatically and the claim is discarded if it does not match exactly. Keep it under 40 words: choose the sentence that carries the commitment.

Only quote the named person. If a document reports what someone else said, or a journalist's question, that is not this person's position.

## Describe, never judge

`position_fr` states what the person committed to, in one neutral sentence. `contexte_fr` explains what it means in practice — the scheme, body, law or standard being referred to.

Never evaluate. Words like *ambitieux, flou, réaliste, timide, irréaliste, audacieux* are rejected automatically. "Proposes a 23 Md€ investment" is a description. "Proposes an ambitious investment" is a judgement.

`position_en` and `contexte_en` are the same content in English. `quote_gloss_en` translates the quote as a reading aid — the French quote remains the evidence.

## Axes

Classify each position into exactly one:

{axes}

If a position genuinely fits none of these, do not invent a fit — leave it out and it will be picked up by a human."""


def system_prompt() -> str:
    axes = "\n".join(f"- **{k}** — {v}" for k, v in AXES.items())
    return SYSTEM.format(axes=axes)


def user_prompt(person_name: str, title: str | None, text: str) -> str:
    head = f"Person: {person_name}\nDocument: {title or '(untitled)'}\n\n---\n\n"
    return head + text


def prompt_hash() -> str:
    """Recorded with every batch. A claim is explained by its prompt as much as
    by its model."""
    return hashlib.sha256(system_prompt().encode()).hexdigest()[:16]
