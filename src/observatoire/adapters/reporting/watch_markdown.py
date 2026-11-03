"""WatchReport -> the editors' daily Markdown note (French: it is read by people)."""

from observatoire.domain.watch import (
    CandidateLead,
    LeadKind,
    TopicSignal,
    WatchReport,
    needs_review,
)

_LEAD_TEXT = {
    LeadKind.DECLARED_NOT_LISTED: "déclaré·e selon la liste extérieure, absent·e du registre",
    LeadKind.WITHDRAWN_BUT_LISTED: (
        "retrait selon la liste extérieure, encore « en course » chez nous"
    ),
    LeadKind.DECLARED_BUT_WITHDRAWN_HERE: (
        "déclaré·e de nouveau selon la liste extérieure, « retiré·e » chez nous"
    ),
}
_MAX_EMPTY = 15


def _lead(lead: CandidateLead) -> str:
    when = f", le {lead.on.isoformat()}" if lead.on else ""
    party = f" ({lead.party})" if lead.party else ""
    return f"- **{lead.name}**{party} : {_LEAD_TEXT[lead.kind]}{when}"


def _signal(signal: TopicSignal, report: WatchReport) -> list[str]:
    review = needs_review(signal, report.topic_threshold, report.topic_min_candidates)
    flag = " — **à examiner**" if review else ""
    who = ", ".join(signal.candidates) or "personne"
    lines = [f"### {signal.topic.label_fr} : {signal.passages} passage(s){flag}", f"Qui : {who}"]
    lines += [f"- {e.candidate_id} — « {e.excerpt} » ({e.url})" for e in signal.examples]
    return [*lines, ""]


class WatchMarkdown:
    def render(self, report: WatchReport) -> str:
        lines = [
            f"# Veille du {report.generated_at:%d/%m/%Y %H:%M} (UTC)",
            "",
            "Propositions pour l'équipe éditoriale. **Rien n'a été modifié automatiquement** :",
            "ajouter un candidat (`config/candidates.yaml`, règle d'inclusion) ou un axe",
            "(`config/taxonomy.yaml`, nouvelle version de consigne) est une décision éditoriale.",
            "",
            "## Candidats à examiner",
            "",
            f"Source : {report.roster_label}. Une piste, pas une preuve : vérifier la déclaration",
            "et le critère de représentativité avant toute inscription.",
            "",
        ]
        if report.roster_error:
            lines.append(f"Liste extérieure illisible aujourd'hui : {report.roster_error}")
        else:
            lines += [_lead(lead) for lead in report.candidate_leads] or ["Rien à signaler."]
        lines += [
            "",
            "## Sujets à examiner",
            "",
            "Sujets qui ne sont pas des axes, comptés dans les passages qui parlent d'IA.",
            f"À partir de {report.topic_threshold} passages venant d'au moins"
            f" {report.topic_min_candidates} candidats, le sujet mérite peut-être un axe.",
            "",
        ]
        for signal in report.topic_signals:
            lines += _signal(signal, report)
        lines += [
            "## Passages sur l'IA",
            "",
            f"- {report.ai_passages} passage(s) passent le filtre IA dans la fenêtre de collecte.",
            f"- {report.pending_passages} en attente d'annotation par l'annotateur courant.",
            f"- {len(report.empty_passages)} annotés sans déclaration : le plus souvent une",
            "  mention en passant (réponse correcte), parfois un sujet qu'aucun axe ne couvre.",
            "",
        ]
        lines += [
            f"  - {e.candidate_id} — « {e.excerpt} » ({e.url})"
            for e in report.empty_passages[:_MAX_EMPTY]
        ]
        if len(report.empty_passages) > _MAX_EMPTY:
            lines.append(f"  - … et {len(report.empty_passages) - _MAX_EMPTY} autre(s)")
        return "\n".join(lines) + "\n"
