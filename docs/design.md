# Design — tagging validation and how Juno is measured

> **Status, 27 September 2026.** This is the design record for checking the LLM's labels
> (checkpoints 1 and 2), written 20–25 September. The code in `tagger/` follows it and cites its
> sections. Some parts describe plans that changed later: the answering and judge models in
> Appendix A were replaced, because every Claude model is rate-limited to zero for real-time calls in
> this workspace (both approaches use Llama 3.3 70B; the judge is Qwen 3.5 122B), and the
> measurements in section 9 stop at the trials. The final results and the current design are in the
> [README](../README.md).

This document extends the design document submitted on 2026-09-17 (`design-doc.pdf`). It does not
contradict the submission. It makes two things concrete: how the labels that Juno counts are proved
good enough to count, and how Juno's score is kept separate from the quality of those labels.

It was rewritten on 2026-09-20 to record the decisions the project owner took that day. The body
refers to AI models by their role. Model names and platform specifics are in Appendix A. The
calculations behind the judgement numbers are in Appendix B.

## Terms used in this document

| Term | Meaning |
|---|---|
| Sentence | One of the 5,152 English restaurant-review sentences in the dataset. |
| Topic | What a sentence is about. The dataset fixes 12 topics. Section 4.3 lists them. |
| Sentiment | Positive, negative or neutral. Neutral is rare (109 sentences) and no test question asks about it. |
| Label | One sentence, one topic and one sentiment together. A sentence can carry several labels. |
| Human labels | The labels that came with the dataset, made by people. They are treated as the truth. Table `human_labels`. |
| Tagger | The AI model that reads each sentence and writes its own labels. Table `review_facts`. |
| Instructions | The page of text the tagger follows. It lists the 12 topics and says how to label. |
| Juno | The agent that answers questions about the reviews. It answers a counting question by counting the tagger's labels. It never sees the human labels. |
| "How many" question | A test question such as "How many review sentences mention the service negatively?" Each one is about one topic and one sentiment. There are 18. Section 4.2 lists them. |

Earlier versions of this document used other words. They called checkpoint 1 "the gate", the
instructions "the prompt", one attempt at checkpoint 1 "a round", and the trial run "the sample".

## 1. The problem this solves

Juno answers "How many review sentences mention the service negatively?" by counting labels. The
true answer is 466, because 466 sentences carry that human label. Juno does not count the human
labels. It counts the tagger's labels, because real reviews do not come with human labels.

So a wrong answer can come from two different places.

| Where it goes wrong | Example |
|---|---|
| The tagger's labels are wrong | The tagger finds 400 of the 466 service complaints. Juno counts correctly and answers 400. |
| Juno mishandles a correct count | The count is 466 and Juno's answer says "about 500". |

One accuracy number cannot tell these apart. "Juno is 85% accurate" could not be defended, because
nobody could say which part caused the other 15%. This design measures the two parts separately. It
also refuses to build Juno on labels that have not been checked.

## 2. Order of work

```
write the tagger's instructions
        │
        ▼
trial run: the tagger labels 1,500 sentences  ◀──────────┐
        │                                                │
        ▼                                                │
CHECKPOINT 1 ── fails ──▶ adjust the instructions ───────┘
        │
      passes
        ▼
full run: the tagger labels all 5,152 sentences, once
        │
        ▼
CHECKPOINT 2: measured once. The tagger is not changed afterwards.
        │
        ▼
build Juno
```

Both checkpoints come after the tagger has labelled something, because a checkpoint compares the
tagger's labels with the human labels. They differ in how much has been labelled and in what may
happen next.

| | Checkpoint 1 | Checkpoint 2 |
|---|---|---|
| Comes after | The trial run, 1,500 sentences | The full run, all 5,152 sentences |
| Comes before | The full run | Building Juno |
| "How many" questions it can mark | 10 of the 18 | All 18 |
| How often | Repeated while the instructions are improved | Once |
| May the tagger be adjusted afterwards? | Yes | No |
| What it decides | Whether to stop adjusting and label everything | Which questions the labels can support |

The labels from a trial run are used for checkpoint 1 and then discarded. The full run labels all
5,152 sentences, including the 1,500 again. Juno only ever counts the labels from the full run.

## 3. What is measured

| Measure | Plain meaning | Where it is used |
|---|---|---|
| Count closeness | For one "how many" question: how far the tagger's count is from the human count, as a percentage of the human count. | Checkpoint 1, condition 1. Checkpoint 2. |
| F1 score | For one topic: how closely the tagger's labels match the human labels, from 0 to 1. Section 4.3 gives the formula. | Checkpoint 1, condition 2. Reported at checkpoint 2. |
| Juno's own accuracy | Juno answering from the human labels, as if the tagger were perfect. A diagnostic. | The results table, section 10. |
| System accuracy | Juno answering from the tagger's labels. The headline. | The results table, section 10. |

Count closeness and the F1 score are different, and both are needed. A count can be right while the
sentences behind it are wrong, because missed labels and wrong labels cancel out. Here is a small
case. The numbers are made up.

| | Sentences labelled "the service, negative" | Total |
|---|---|---|
| Humans | Sentences 1 to 10 | 10 |
| Tagger | Sentences 1 to 5, and sentences 11 to 15 | 10 |

The totals match, so count closeness is perfect. But the tagger missed 5 real complaints and labelled
5 sentences that are not complaints. Its F1 score is 0.50. Section 4.3 shows the working.

## 4. Checkpoint 1

Checkpoint 1 decides whether the tagger's instructions are good enough to stop adjusting them. The
tagger must meet two conditions. If it fails either one, the instructions are adjusted and the trial
run is repeated.

### 4.1 The trial run uses 1,500 sentences

**Why only part of the sentences.** Each time someone studies the tagger's mistakes and adjusts the
instructions, the instructions become fitted to the sentences that were studied. If that were done on
all 5,152 sentences, the tagger's final score would flatter it, like a student who practised on the
real exam paper. So adjusting happens on a part, and the rest stays unseen.

**How the part is chosen.** Every sentence has an id made by scrambling its text. The sentences are
sorted by that id and the first 1,500 are taken. The pick is effectively random and is the same every
time. 1,500 ÷ 5,152 is 29% of the data. That leaves 5,152 − 1,500 = 3,652 sentences that no adjusting
ever touches.

**Why 1,500.** Decided by the project owner on 2026-09-20. The three attempts before that used 500. A
bigger trial run lets more questions be marked (section 4.2), but leaves fewer untouched sentences. A
calculation on a laptop compared four sizes using two imaginary taggers. The good one should pass. The
bad one should fail. Appendix B gives the assumptions.

| Trial run size | Share of the data | Questions that can be marked, of 18 | Ticks needed (80%, rounded up) | Good tagger passes | Bad tagger passes | Sentences never used for adjusting |
|---|---|---|---|---|---|---|
| 500 | 10% | 6 | 5 (80% of 6 is 4.8) | 76% | 0% | 4,652 |
| 1,000 | 19% | 9 | 8 (80% of 9 is 7.2) | 71% | 0% | 4,152 |
| 1,500 | 29% | 10 | 8 (80% of 10 is 8) | 96% | 0% | 3,652 |
| 2,000 | 39% | 10 | 8 (80% of 10 is 8) | 99% | 0% | 3,152 |

Every size rejects the bad tagger. They differ in how often a good tagger is wrongly rejected. 1,000
does worse than 500 because 80% of 9 rounds up to 8, which leaves room for only one unlucky cross.
2,000 marks the same 10 questions as 1,500. An 11th question would need about 2,061 sentences,
because its full size is 75 and 30 ÷ 75 × 5,152 = 2,061. 1,500 was chosen over 2,000 because three
points of reliability were not worth 500 fewer untouched sentences. This is a sanity check, not a
proof.

### 4.2 Condition 1 — the counts are close

**The rule.** For each "how many" question, the tagger's count is compared with the human count
inside the 1,500 sentences. The question gets a tick if the tagger's count is within 10% of the human
count. At least 80% of the marked questions must have a tick.

The 10% and the 80% come from Juno's own target in the submitted design: within 10% on at least 80%
of counting questions. Juno's answer is the tagger's count. So if the tagger cannot meet that target,
Juno cannot either, however well it is built.

**Questions with fewer than 30 sentences in the trial run are not marked.** Inside 1,500 sentences,
every question shrinks to about 29% of its full size.

| Question is about | Human count in all 5,152 | Human count in the 1,500 | 10% of that | What one or two borderline sentences do |
|---|---|---|---|---|
| the service, negatively | 466 | about 136 | 13 sentences | Nothing. The tagger may be off by 13 and still get a tick. |
| prices, negatively | 36 | about 10 | 1 sentence | They decide the mark. Off by 2 is 20%, which is a cross. |

Two careful people would disagree on two sentences. So a cross on a 10-sentence question says the
question was too small to mark. It does not say the tagger is bad. Such questions are still printed in
the report. They do not count towards pass or fail.

**The 18 "how many" questions, and which ones checkpoint 1 can mark.** There are 12 topics and 2
sentiments that are asked about, which gives 24 combinations. When the test questions were
generated, a "how many" question was written only for combinations with at least 30 sentences in the
full data. That left 18.

| Question is about | Human count in all 5,152 | Human count in the 1,500 (× 29%) | Marked at checkpoint 1? | Marked at checkpoint 2? |
|---|---|---|---|---|
| the food, positively | 1,889 | 550 | yes | yes |
| the restaurant overall, positively | 1,083 | 315 | yes | yes |
| the service, positively | 799 | 233 | yes | yes |
| the food, negatively | 510 | 148 | yes | yes |
| the service, negatively | 466 | 136 | yes | yes |
| the atmosphere, positively | 350 | 102 | yes | yes |
| the restaurant overall, negatively | 296 | 86 | yes | yes |
| the menu choices, positively | 229 | 67 | yes | yes |
| the drinks, positively | 198 | 58 | yes | yes |
| the atmosphere, negatively | 124 | 36 | yes | yes |
| food prices, positively | 75 | 22 | no | yes |
| the location, positively | 64 | 19 | no | yes |
| the menu choices, negatively | 62 | 18 | no | yes |
| prices, positively | 45 | 13 | no | yes |
| food prices, negatively | 44 | 13 | no | yes |
| other aspects, positively | 42 | 12 | no | yes |
| prices, negatively | 36 | 10 | no | yes |
| the drinks selection, positively | 35 | 10 | no | yes |

Ten questions are marked, so the pass mark for condition 1 is 8 ticks of 10.

**Where the number 30 comes from.** It is a judgement number. An earlier AI session set it in
`eval/question_generator.py` (`MIN_SUPPORT = 30`) to decide which questions to write, and this document
reuses it to decide which questions to mark. Nobody recorded why it is 30 and not 20 or 40. It was
checked afterwards, on 2026-09-20, with the same imaginary good tagger and a trial run of 1,500.

| Minimum size for a question to be marked | Questions marked, of 18 | Ticks needed | Good tagger passes checkpoint 1's count condition |
|---|---|---|---|
| none | 18 | 15 | 31% |
| 20 | 11 | 9 | 91% |
| 30 | 10 | 8 | 96% |
| 50 | 9 | 8 | 90% |

With no minimum, a good tagger is rejected two times in three, because the small questions get
crosses by bad luck. 30 gives the right verdict most often of the values tried. 50 does worse because
9 questions with 8 ticks needed leaves room for only one unlucky cross. The number was kept on this
evidence. Appendix B gives the assumptions.

### 4.3 Condition 2 — an average F1 score of at least 0.60

The tagger's labels are compared with the human labels on the trial-run sentences. A label is one
sentence, one topic and one sentiment together. For each of the 12 topics, every label falls into one
of three groups. *Hits* (H) are labels that both the tagger and the humans gave. *Inventions* (I) are
labels that only the tagger gave. *Misses* (M) are labels that only the humans gave.

The F1 score for a topic is 2 × H ÷ (2 × H + I + M). It runs from 0 to 1. A score of 1 means the
tagger gave exactly the labels the humans gave.

The average F1 score is the 12 topic scores added together and divided by 12. Every topic counts the
same, whether it is common or rare. The tagger meets condition 2 if this average is at least 0.60.

**The same formula in two steps.** A is the share of the tagger's labels that were right: H ÷ (H + I).
B is the share of the human labels that the tagger found: H ÷ (H + M). The F1 score is
2 × A × B ÷ (A + B). Both forms always give the same number. The score is built this way so that a
high A cannot hide a low B, or the other way round.

**Worked case, from section 3.** Hits 5, inventions 5, misses 5. The score is
2 × 5 ÷ (2 × 5 + 5 + 5) = 10 ÷ 20 = 0.50.

**The 12 topics are fixed by the dataset**, not chosen by this project: three for food, three for
drinks, three for the restaurant as a whole, and one each for service, atmosphere and location.
3 + 3 + 3 + 1 + 1 + 1 = 12.

| Subject | Topics, as named in the test questions |
|---|---|
| Food | the food; the menu choices; food prices |
| Drinks | the drinks; the drinks selection; drink prices |
| The restaurant as a whole | the restaurant overall; prices; other aspects of the restaurant |
| Service | the service |
| Atmosphere | the atmosphere |
| Location | the location |

**Why rare topics stay in this average**, although condition 1 skips small questions. The two
measures behave differently on small numbers. Take a topic with 12 sentences in the trial run. The
taggers are made up.

| | Count closeness | F1 score |
|---|---|---|
| Good tagger: 10 hits, 0 inventions, 2 misses | 10 against 12 is 16.7% off: a cross | 20 ÷ (20 + 0 + 2) = 0.91 |
| Bad tagger: 2 hits, 9 inventions, 10 misses | 11 against 12 is 8.3% off: a tick | 4 ÷ (4 + 9 + 10) = 0.17 |

Count closeness gets both verdicts the wrong way round. The F1 score still tells the good tagger from
the bad one. At checkpoint 1 it is also the only early signal about the rare topics, and checkpoint 1
is the only stage where the instructions can still be adjusted.

**Where the number 0.60 comes from.** The submitted design lists the tagger's F1 score against the
human labels as something to measure, with no pass mark. An earlier AI session added the pass mark of
0.60 on 2026-09-20, in `tagger/checkpoints.py` (`MIN_MACRO_F1 = 0.60`), before the first attempt ran. It
recorded no reason. The number is not derived from Juno's targets or from anything else. It is a
judgement number. The project owner decided on 2026-09-20 to keep it, averaged over all 12 topics.
Changing it straight after an attempt that scored 0.59 would look like moving the bar to fit the
result.

A score of 0.60 is a loose minimum. For a topic with 100 human labels it could mean 60 hits, 40
inventions and 40 misses: 120 ÷ (120 + 40 + 40) = 0.60.

### 4.4 Kept unchanged from the earlier version

**If the gate cannot be passed** after three prompt or model rounds, stop and choose explicitly:

1. Accept the ceiling, lower Juno's count target to what the tagger supports, and report the
   measurement as the reason; or
2. Narrow the claim to the categories that do pass, and report the rest as a limitation.

Either way the decision and its evidence go in the log and the README. Silently proceeding is not an
option.

## 5. Checkpoint 2

**What it is for.** Checkpoint 1 cannot mark 8 of the 18 "how many" questions, because each has fewer
than 30 sentences inside the trial run. Juno needs at least 80% of its counting questions right. So
checkpoint 1 can pass while Juno's target is already out of reach. The 8 unmarked questions are the
rare topics, which is where the tagger has been weakest (section 9). Checkpoint 2 exists to mark them
before Juno is built. Added by decision of the project owner on 2026-09-20.

**How it works.** After the full run, the tagger's count is compared with the human count for all 18
questions, on all 5,152 sentences. Every question now has its full size, and the smallest has 35
sentences, so none is skipped. Each question gets a tick if the tagger's count is within 10% of the
human count, and a cross if not. It costs nothing extra to run, because the full run is needed anyway
for Juno to have labels to count.

**Worked case.** "The location, positively" has 19 sentences inside the trial run. 10% of 19 is 1.9,
so one borderline sentence could decide its mark, and checkpoint 1 skips it. On the full data it has
64 sentences. 10% of 64 is 6.4, so the tagger gets a tick with any count from 58 to 70. It would have
to be off by 7 sentences to get a cross. A mark here says something about the tagger.

**What a cross means for Juno.** Juno's answer to a "how many" question is the tagger's count. The
tagger counts below are made up.

| Question is about | Human count | Tagger's count (made up) | How far off | Checkpoint 2 mark | Juno's answer if Juno itself works perfectly | Juno is marked |
|---|---|---|---|---|---|---|
| the service, negatively | 466 | 480 | 3.0% | tick | 480 | right |
| the location, positively | 64 | 41 | 35.9% | cross | 41 | wrong |

A cross means Juno will get that question wrong even if Juno itself is built perfectly. A tick means
Juno will get it right as long as its own part works: understanding the question and reporting the
number faithfully.

**It runs once, and the tagger is not changed afterwards.** This is what keeps checkpoint 2 from
defeating the purpose of the trial run. Looking at all the data does no harm. Adjusting the tagger
because of what was seen does. After checkpoint 2 the instructions are still fitted only to the 1,500
trial sentences, exactly as before. If someone read the 23 missed location sentences and added a line
to the instructions to catch them, the next count would look better only because the instructions had
been written with the answers in view. Juno is tested on these same 5,152 sentences, so its score
would be inflated too.

**Why not a fresh 30% instead, with 40% kept unseen.** In a fresh 1,500 sentences the 8 small
questions would again have about 22, 19, 18, 13, 13, 12, 10 and 10 sentences. None could be marked, so
the checkpoint would repeat checkpoint 1. Holding data back also protects nothing here, because
checkpoint 2 adjusts nothing. And it is not estimating anything: it compares the exact counts that
Juno will report with the exact true answers.

**The F1 scores are also reported at checkpoint 2**, for every topic and sentiment. They are not a
pass or fail condition there.

## 6. What the report says when checkpoint 2 gives crosses

The tagger cannot be changed after checkpoint 2. So if the crosses put Juno's target out of reach,
the only open choice is what the report says. The project owner decided on 2026-09-20, before any
result existed, so that the rule cannot be accused of being chosen to flatter the result.

**The rule.**

- The 80% target stays fixed.
- The headline is system accuracy on all the scored questions.
- If the target is missed, it is reported as missed.
- The questions that got a cross at checkpoint 2 are listed by name, with the human count and the
  tagger's count, as a limitation.
- Juno's score on the remaining questions is shown separately and labelled for what it is: a measure
  of whether Juno's own part works.

**Why the second number cannot be the headline.** The remaining questions are chosen by comparing the
tagger with the human labels. As section 5 shows, Juno's score on them is nearly guaranteed once
Juno's own part works. It is useful. It is not independent evidence.

**Rejected.** Lowering the target to what the labels support would move the target after the result
was known. Deciding once the numbers were in is what the earlier version of this document said, and
is the choice a reviewer distrusts.

**What the results section would look like.** The outcome is made up: checkpoint 2 gives 13 ticks and
5 crosses, and Juno then gets every ticked question right and every crossed one wrong.

> **Count accuracy.** Target: 80%. Result: 13 of 18 = 72%. **Target missed.**
> **Why.** On 5 of the 18 questions the tagger's count was more than 10% from the human count, so
> Juno could not answer them correctly. They are listed below with both counts.
> **Where Juno can be trusted.** On the 13 questions with reliable labels, Juno got 13 right.
> **What this means for a user.** Trust Juno's counts on common topics. Treat its counts on rare
> topics as rough.

**The real score is taken on 13 questions, not 18.** The evaluation plan sets aside 30% of the test
questions for use while Juno is built, and scores Juno once on the other 70%. Of the 18 "how many"
questions, 5 are set aside and 13 are scored. 80% of 13 is 10.4, so the pass mark is 11 of 13, and
Juno can afford 13 − 11 = 2 wrong answers. Checkpoint 2 still looks at all 18, because it checks the
tagger's labels and not Juno's answers.

**The tagger's general quality is reported from the 3,652 untouched sentences.** Both measures, count
closeness and the F1 score, are worked out on the sentences that no adjusting ever touched. That is
the honest figure for how good the tagger is on text it was not fitted to. It is reported, and it is
not a pass or fail condition. Checkpoint 2 uses all 5,152 sentences for a different reason: Juno is
tested on all of them.

## 7. Which model does the tagging

Juno uses three AI models in three roles. The agent answers the user's question. The judge grades
answer quality, and is deliberately a different model from the agent so that it does not grade its
own style. The tagger labels the sentences. This section is about the tagger. Names are in Appendix A.

### Two ways to call a model on the platform

| Way | What it means | Which role uses it |
|---|---|---|
| One request at a time | Code sends one request to the model and waits for one answer. | The agent and the judge. |
| In bulk | One function of the platform runs the model over every row of a table in a single query. | The tagger, because it has 5,152 sentences to label. |

### What happened, and why

On 2026-09-20 an earlier AI session tried the bulk way with the closed-source model that the agent
uses. The platform refused it. That session then wrote here that no model from that family could be
used for tagging, and switched the tagger to an open model. That conclusion was wrong. It went from
one refused model to the whole family, and no other model from the family had been tried.

The platform publishes a list of the models it supports for the bulk way. The model that was tried is
not on that list, which explains the refusal. But the list turned out to be a poor guide to this
workspace, in two ways. One model from the same family is on the list and is still refused here. Four
others on the list are not offered in this workspace at all.

### What this workspace accepts

So the question was settled by asking the workspace. On 2026-09-20 every chat model the workspace
offers was put through the bulk function on two rows of the sentence table. The prompt was a fixed
instruction followed by the row's id, so no review text was sent. A refusal costs nothing. An
acceptance costs two calls of a few words. The check reproduced the first refusal word for word, so it
tests the right thing.

| Kind of model | Offered by the workspace | Accepted for bulk use |
|---|---|---|
| Closed-source, from the family the agent and the judge come from | 3 | 1 |
| Open | 8 | 8 |

The one closed-source model that is accepted is neither the agent's model nor the judge's. Appendix A
lists every model, the platform's exact messages, and the documentation's list beside them.

**The lesson.** Documentation says what a platform supports in general. Only the workspace says what
it accepts. Whatever a later step relies on is checked in the workspace first.

### The plan

Decided by the project owner on 2026-09-20, after that check. There are two candidates. Both are
accepted for bulk use in this workspace.

1. **The preferred candidate** is the one closed-source model the workspace accepts for bulk use. It
   keeps the agent, the judge and the tagger as three different models.
2. **The second candidate** is one open model. The project owner named it, and the project log
   recorded it, before its first trial run. Only that one is tried. The rule stops shopping around:
   every extra model tried is another chance for one to look good by luck.

Appendix A names both. The open model that made the first three attempts is no longer a candidate.

One other route exists and is not planned: calling a model one sentence at a time from code, the way
the agent and the judge are called. It would work with any model. It is slower and needs new code.

### How the better model is picked

Both candidates are run. The comparison is fair only if one thing differs: both get identical
instructions, the same 1,500 trial sentences and the same marking. It happens at checkpoint 1, the
only place where choosing is allowed. Checkpoint 2 is never used to choose between models.

Checkpoint 1 gives each model two results: ticks out of 10 (section 4.2) and an average F1 score
(section 4.3). They can disagree. The winner is picked in this order, fixed before any result exists.

1. A model that meets both conditions beats one that does not.
2. If both meet them, or neither does, the higher average F1 score wins.
3. If the average F1 scores are equal to two decimal places, the model with more ticks wins.
4. If still equal, the preferred order decides, as given in Appendix A.

**Why the F1 score comes first.** Ticks are whole numbers out of 10, and in the calculation in
Appendix B a good tagger lost about one tick in ten to luck, so a gap of one tick means little. At
checkpoint 1 only the F1 score sees the rare topics. And a count can be right by cancellation, while
an F1 score cannot.

**One caution for the results.** A gap of 0.01 in the average F1 score could be luck. Both numbers are
shown so a reader can see how close it was.

**Neither candidate has a home advantage.** The current instructions were adjusted three times against
the mistakes of a third model, the one that made the first three attempts. They were never adjusted
against either candidate.

### What is not yet known

- What a tagging run costs with each candidate. The runs so far, made with a third model, are recorded
  only as costing "cents". The preferred candidate belongs to the most expensive tier of its family. A
  first figure comes from a test on five sentences, before any trial run of 1,500 is approved.
- Whether each candidate's replies come back in a form the notebook can read. The two-row check shows
  that a model is accepted. It does not show what its labels look like.

## 8. Discipline for the tagger's instructions

- The instructions are kept in code, in `tagger/prompt.py`, so that changes can be reviewed.
- **No dataset sentences in the instructions.** The examples in them are written by hand. A real
  labelled sentence would leak the truth into the part of the system that answers questions.
- Adjusting happens on the trial-run sentences only. The full data is labelled once, with the chosen
  instructions.
- The tagger sees one sentence and the list of topics. It never sees the human labels or the test
  questions.

## 9. Measurements so far

Three attempts were made on 2026-09-20. All three used the same open model (Appendix A) and a trial
run of 500 sentences. Only the instructions changed.

| Attempt | What changed in the instructions | Questions with a tick | Average F1 score |
|---|---|---|---|
| 1 | A list of the 12 topics only | 20% | 0.51 |
| 2 | Added what each topic covers and what it does not | 30% | 0.53 |
| 3 | Reworded so that a sentence about several topics gets a label for each | 35% | 0.59 |

**What went wrong in each.**

- Attempt 1 gave too many labels for small topics. The drinks selection came out 350% too high and
  the menu choices 127% too high. The restaurant overall came out 31% too low.
- Attempt 2 overcorrected. A line saying most sentences cover one topic made the tagger give too few
  labels. The restaurant overall, negatively, came out 46% too low, and the service, positively, 23%
  too low.
- Attempt 3 is strong on the big topics and weak on the rare ones. The project log records four of
  its twelve topic scores.

| Topic | F1 score, attempt 3 |
|---|---|
| the food | 0.83 |
| the service | 0.84 |
| the location | 0.27 |
| other aspects of the restaurant | 0.09 |
| The other eight topics | Not recorded. They average about 0.63, because 0.59 × 12 = 7.08, the four recorded scores add up to 2.03, and (7.08 − 2.03) ÷ 8 = 0.63. |

The pattern is consistent: **the tagger is good where there is data and poor where there is not.**
That is worth reporting as a finding, because a chatbot that answers from a handful of retrieved
sentences is weakest on rare topics too.

**These three attempts were marked under rules that have since been replaced.** They used 500
sentences, and every question was marked, including ones with 2 or 3 sentences in the trial run. In
the calculation in Appendix B, a good tagger passes that marking 1.9% of the time, and gets a tick on
about 56% of questions on average. So the three failures say little about condition 1. The "questions
with a tick" column cannot be compared with results under the current rules. The average F1 scores
were not affected by that marking, though they were measured on 500 sentences and not 1,500.

Nothing has touched the full data. The table `review_facts` does not exist yet.

## 10. Reporting

The results table presents three numbers, not one.

```
Juno's own accuracy   (Juno answering from the human labels; diagnostic)
system accuracy       (Juno answering from the tagger's labels; the headline)
difference            = the cost of imperfect labels
```

Rules that keep this honest:

- Juno's own accuracy is measured only on the questions set aside for building Juno, never on the
  scored questions.
- It is labelled a diagnostic everywhere it appears.
- The comparison between Juno and the baseline chatbot stays system against system. Comparing the
  baseline's end-to-end score with Juno's diagnostic score would be meaningless.
- Section 6 governs what is said when the labels put the target out of reach.

## Appendix A — model names and platform specifics

The body of this document refers to models by role. This appendix holds the names.

**The platform** is Azure Databricks, in the East US region.

**Models by role.**

| Role | Model | Endpoint | How it is called |
|---|---|---|---|
| Agent | Claude Sonnet 5 | `databricks-claude-sonnet-5` | One request at a time |
| Judge | Claude Opus 5 | `databricks-claude-opus-5` | One request at a time |
| Tagger, preferred candidate | Claude Opus 4.8 | `databricks-claude-opus-4-8` | In bulk |
| Tagger, second candidate | Llama 3.3 70B Instruct | `databricks-meta-llama-3-3-70b-instruct` | In bulk |
| Tagger for the three attempts of 2026-09-20. No longer a candidate. | gpt-oss-120b | `databricks-gpt-oss-120b` | In bulk |

**The preferred order** used as the last tie-break in section 7 is Claude Opus 4.8, then Llama 3.3
70B Instruct.

**The bulk function** is the Databricks SQL function `ai_query`, run over a table. Databricks calls
this batch inference.

**The first error**, returned on 2026-09-20 when Claude Sonnet 5 was tried in bulk:

    Endpoint databricks-claude-sonnet-5 is not supported for batch inference

**The documentation's bulk list.** Source: Azure Databricks documentation, "Use ai_query",
https://learn.microsoft.com/en-us/azure/databricks/large-language-models/ai-query, page dated
2026-09-11, read on 2026-09-20. The text models it lists as supported for batch inference: Claude
Opus 5, Opus 4.8, Opus 4.7, Opus 4.6, Sonnet 4.6 and Sonnet 4; gpt-oss 120b and 20b; Llama 4 Maverick,
Llama 3.3 70B Instruct and Llama 3.1 8B Instruct; Qwen 3.5 122B and Qwen3-Next 80B; Gemma 3 12B. The
same page says that hosted models outside the list "are made available for real-time inference".

**What this workspace offers and accepts**, checked on 2026-09-20. The workspace offers 11 chat
models and 3 embedding models.

| Model | Offered here | On the documentation's bulk list | The bulk function in this workspace |
|---|---|---|---|
| Claude Opus 4.8 | Yes | Yes | **Accepted** |
| Claude Opus 5 | Yes | Yes | **Refused**: "Endpoint databricks-claude-opus-5 is not supported for batch inference" |
| Claude Sonnet 5 | Yes | No | Refused: "Endpoint databricks-claude-sonnet-5 is not supported for batch inference" |
| Claude Sonnet 4.6 | No | Yes | "Endpoint with name 'databricks-claude-sonnet-4-6' does not exist", under both name forms |
| Claude Opus 4.7, Opus 4.6, Sonnet 4 | No | Yes | Not tried. No endpoint is listed for them. |
| gpt-oss 120b, gpt-oss 20b | Yes | Yes | Accepted |
| Llama 4 Maverick, Llama 3.3 70B Instruct, Llama 3.1 8B Instruct | Yes | Yes | Accepted |
| Qwen 3.5 122B, Qwen3-Next 80B | Yes | Yes | Accepted |
| Gemma 3 12B | Yes | Yes | Accepted |

So the documentation and the workspace disagree about Claude Opus 5, and the workspace is the
authority.

**How it was checked.** One statement per model, through the workspace's SQL warehouse:

    SELECT sentence_id,
           ai_query('<model>', CONCAT('Reply with the single word OK. Ignore this id: ', sentence_id)) AS reply
    FROM (SELECT sentence_id FROM juno.restaurant.sentences ORDER BY sentence_id LIMIT 2)

The argument depends on the row, which is what makes it the bulk form. Nothing was created or changed.
The cost was two calls of a few words for each accepted model, 18 calls in all, and a few minutes of
the SQL warehouse.

**The two name forms are one thing.** The documentation names models as `system.ai.<name>`. Juno's
code names them as `databricks-<name>`. The endpoint listing shows that each `databricks-<name>`
endpoint serves the catalogue model `system.ai.<name>`. When the bulk function was given
`system.ai.claude-sonnet-4-6`, the platform turned it into `databricks-claude-sonnet-4-6` and reported
that no such endpoint exists. There is no second place where a model could be.

**How the two candidates were chosen.** The project owner first chose Claude Sonnet 4.6, on
2026-09-20, because it was on the documentation's list, was not marked deprecated, and Sonnet models
are priced below Opus models. The check then showed it does not exist in this workspace, and that
Claude Opus 4.8 is the only Claude model the bulk function accepts here. The project owner then chose
Claude Opus 4.8 and a Llama model as the two candidates, and named Llama 3.3 70B Instruct: Databricks's
own bulk-labelling examples use it, and the 8B model is expected to be the weakest of the three at
telling 12 similar topics apart. That is a judgement, not a measurement. No Llama model and no Claude
model has labelled any of these sentences. Llama 4 Maverick would also have been a reasonable choice.

**Not yet known.**

- What a tagging run costs with Claude Opus 4.8 and with Llama 3.3 70B Instruct. Opus models are
  priced above Sonnet models; no figure for this workspace is in hand.
- Whether each candidate's replies come back in a form the notebook can read.

## Appendix B — the calculations behind the judgement numbers

All of these ran on a laptop on 2026-09-20. They use random numbers only. They use none of the
project's data, make no model calls and touch nothing on Databricks. They are sanity checks, not
proofs.

**The imaginary taggers.**

| Tagger | How it behaves | Its counts, on average | What should happen to it |
|---|---|---|---|
| Good | Misses 17% of the true labels, about 1 in 6. Adds wrong labels at the same average rate. | Exactly right | It should pass |
| Bad | Misses 25% of the true labels. Adds wrong labels at a rate of 10%. | 15% too low | It should fail |

The good tagger's error rates were chosen to match an F1 score of about 0.83, which is what the real
tagger reached on its two biggest topics in attempt 3. Every mistake is assumed to be independent of
every other. Real mistakes are probably not fully independent, which is one reason these are sanity
checks only.

**The method.** For each question, the number of missed labels and the number of wrong labels are
drawn at random. The question gets a tick if the difference is within 10% of the human count. The
whole of condition 1 is then applied. This is repeated 20,000 times for each row of the tables in
sections 4.1 and 4.2, and 200,000 times for each row of the table below.

**How often the good tagger gets a cross on one question, by luck alone.**

| Human count for the question | 10% of that, in whole sentences | Good tagger gets a cross |
|---|---|---|
| 5 | 0 | 66% |
| 10 | 1 | 38% |
| 20 | 2 | 31% |
| 30 | 3 | 25% |
| 50 | 5 | 16% |
| 100 | 10 | 6% |

There is no sharp line at 30. The figures improve gradually. 30 earns its place through the
whole-checkpoint result in section 4.2, not through this table.

**The rules the first three attempts were marked under.** 500 sentences, no minimum size, 20
combinations marked, 16 ticks needed. The good tagger passes 1.9% of the time and gets a tick on 56%
of questions on average.
