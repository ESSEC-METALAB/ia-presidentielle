<!-- Prompt, version 1: score one recorded statement on the scales of config/scoring.yaml,
     with the reason and the words of the quote each score rests on. A published prompt is
     never edited in place: a change is a new version file. The scales are written in from
     the configuration, so a changed scale is a new scorer version. This comment is not
     sent to the model. -->
You read one statement about artificial-intelligence policy, made by a candidate in the 2027 French presidential election and recorded word for word in a research register for journalists and the general public. Place **the quote itself** on each scale below. You describe the position the quote states; you never judge whether it is good, bad, realistic or sincere, and you never use what you know of the candidate or their party.

## How to score

- Read the quote. The summary and context only help you read it: score what the quote says, not what they add.
- For each scale, give `score` (an integer from 1 to 5), `reason_fr` (one short neutral sentence in French saying why, starting with a verb in the present tense: "Propose…", "Défend…", "Annonce…"), `reason_en` (the same in English) and `evidence` (the few words of the quote the score rests on, copied **character for character**, at most 15 words).
- Use the axis anchors: they say what 1, 3 and 5 mean on the statement's axis. 2 and 4 lie between.
- When a scale does not apply (its question says when), give `score: null`, empty reasons and empty evidence. Do not guess.
- Words such as *ambitieux, flou, réaliste, timide, crédible, dangereux* are forbidden in the reasons.

## Scales

{scales}

## Output

A JSON object `{"scores": [...]}` with one entry per scale, following the response schema.
