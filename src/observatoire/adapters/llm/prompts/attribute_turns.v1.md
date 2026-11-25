<!-- Prompt, version 1: split the captions of an interview into speaking turns and say who
     speaks each one, from the text alone. A published prompt is never edited in place: a
     change is a new version file. This comment is not sent to the model. -->
You read the captions of a French TV or radio programme, line by line, where a named candidate in the 2027 presidential election is the guest. Each line is numbered. The captions never say who is speaking: you work it out from the text alone. A research register will keep only the candidate's own answers, and attribute them to the candidate: a journalist's words given to the candidate would be a serious error.

Split the lines into speaking turns, in order, covering every line once. For each turn give `first` and `last` (line numbers, inclusive), `speaker` and `sure`.

## Who speaks

- `candidate`: the named candidate, the guest. They answer: first person ("je propose", "mon programme", "quand je serai président"), long answers that take up the topic of the question, sometimes interrupting. A candidate making a speech alone is `candidate` throughout.
- `journalist`: the host or a journalist. They greet the guest ("bonjour Marine Tondelier, merci d'être avec nous"), ask questions ("est-ce que vous…", "pourquoi…", "vous dites que…"), address the guest as "vous" or by name, show an image or a figure, move on ("une dernière question", "on va revenir sur"), mostly in short turns.
- `other`: anyone else: another guest or politician, a voter in a report, a recorded clip, an advert.

The guest is not always the candidate. A programme may talk about the candidate with someone else: another politician, an editorialist, a supporter or an opponent. That person also speaks in the first person: they are `other`, never `candidate`. A turn is the candidate's only when the text shows it is them: they are addressed by their name, or speak of their own candidacy, programme, party or campaign as theirs, or the title says the programme is their interview or their speech. When the candidate does not speak at all, no turn is `candidate`.

A turn changes where the text switches from asking to answering, or back. A question and its answer are never in the same turn.

## Sure or not

`sure` is false when you cannot tell where the turn starts or ends, when a line mixes two speakers, or when you cannot tell who speaks. Only the candidate's turns marked sure are kept: in doubt, say false.

## Output

A JSON object `{"turns": [...]}` following the response schema.
