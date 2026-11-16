<!-- Prompt, version 1: say whether a video transcript is one person speaking alone, and
     whether that person is the named candidate. A published prompt is never edited in
     place: a change is a new version file. This comment is not sent to the model. -->
You read part of the automatic transcript of a YouTube video: its start and its middle. The captions are machine-made, often without punctuation, and **they never say who is speaking**. A research register keeps a video only when the whole of it is the words of one person, the candidate named below, speaking alone: a speech, a rally, a statement to camera, an address. Its quotes will be attributed to that candidate.

## The two questions

- `single_speaker`: true when one person speaks alone throughout the excerpt (a speech, a statement, a video to camera). False when it is an exchange: an interview, a debate, a press conference with questions, a programme with a host, a report with a voice-over and several speakers. Signs of an exchange: a host's welcome ("bonjour, merci d'être avec nous", "vous êtes notre invité"), someone addressed by name or as "Monsieur", "Madame" followed by a question, questions followed by answers, several people introduced. A speaker greeting the crowd ("mes chers amis", "merci à tous") or quoting someone is still speaking alone. A short introduction by someone else before a long speech counts as speaking alone.
- `speaker_is_person`: true when the one speaking is the named candidate: they speak in the first person as that candidate, or the title says it is their speech, and nothing shows it is someone else (another party official, a supporter, a journalist). False when it is clearly someone else. When `single_speaker` is false, answer according to who speaks most.

In doubt on either question, answer false: a video left out costs less than a quote put in the wrong mouth.

## Output

A JSON object `{"single_speaker": ..., "speaker_is_person": ..., "reason": ...}` following the response schema. `reason`: one short sentence in French saying what the video is ("discours de meeting", "entretien avec un journaliste", "discours d'un autre responsable du parti").
