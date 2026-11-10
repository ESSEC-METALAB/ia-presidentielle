<!-- Prompt, version 1: say whether one recorded statement presents AI as an opportunity,
     a threat, both, or neither. A published prompt is never edited in place: a change is
     a new version file, so every framing names the exact prompt that produced it. This
     comment is not sent to the model. -->
You read one statement about artificial-intelligence policy, made by a candidate in the 2027 French presidential election and recorded word for word in a research register. Say how **the quote itself** presents AI. You do not judge the statement, the candidate or AI.

## The four answers

- `opportunity`: the quote presents AI, or what it brings, as a chance, a benefit, progress or a source of power ("l'IA va créer des emplois", "une chance pour la France", "nous devons devenir le troisième pays de l'IA").
- `threat`: the quote presents AI, or what it brings, as a danger, a harm, a loss or a risk to contain ("l'IA va supprimer des métiers", "une menace pour nos libertés", "nous ne pouvons pas laisser ces machines décider").
- `both`: the quote states a chance and a danger.
- `none`: the quote proposes a measure, states a fact or a figure, or criticises an opponent, without saying whether AI is a chance or a danger. **This is the most common answer.** A measure about AI ("créer un cloud souverain", "former les enseignants à l'IA") is `none` unless the quote itself says AI is a chance or a danger.

Do not infer a view the quote does not state. Do not use the summary or the context to find one: they only help you read the quote. In doubt, answer `none`.

## The evidence

For `opportunity`, `threat` and `both`, `evidence` is copied **character for character** from the quote: the few words that state the chance or the danger (at most 15 words; for `both`, the words of one of them). It is checked against the quote automatically; evidence that is not found makes the answer `none`. For `none`, `evidence` is an empty string.

## Output

A JSON object `{"framing": ..., "evidence": ...}` following the response schema.
