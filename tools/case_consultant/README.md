# Case Consultant

An interviewer for industry experts. It asks about one real decision from the
expert's work in thirteen parts, asks clarifying questions that depend on the
answers, and compiles a case design document: the twelve elements a synthetic
environment is built from, a table of numbers with ranges and sources, the open
questions, and a read-back the expert approves.

Live page: <https://claude.ai/artifact/4EnuNAwM63p2BARZPiJ95a> (private to the
owner until shared).

## The interview

| Part | Fills | What it becomes |
|---|---|---|
| 1 You and your work | the expert | where every answer comes from |
| 2 One real decision | decision-maker and goal | the seat being tested and its score |
| 3 The other people | other parties | other seats, scripted or played |
| 4 What you know and what you don't | known and hidden | observation and hidden state |
| 5 What you can do, and what it costs | moves, costs and limits | actions, prices, budget, end conditions |
| 6 What each step tells you | what moves reveal | what each action returns, with error rates |
| 7 How the result is counted | accounting | the score, in money |
| 8 What makes it hard | tension | worlds on each side of the break-even |
| 9 How cases differ | variation | the generator's ranges and frequencies |
| 10 Newcomer, professional, no effort | yardsticks and typical mistakes | reference players and failure labels |
| 11 Three situations | worked situations | golden cases the build must reproduce |
| 12 The numbers | the numbers table | every setting, with a range and a source |
| 13 What I did not ask | what we did not ask | a warning that the template is missing something |
| Read-back | | the expert checks a plain summary; an audit lists what disagrees and what a builder would have to invent |

One case is one decision. Parts 1 to 7 are the situation, part 12 is the
numbers, parts 8 to 11 are the judgment. The numbers pass comes late because
figures turn up in every part.

## Who decides what

The page owns the interview. The model is stateless: each turn it receives the
protocol, the case file so far, what the current part still needs, and the
expert's latest answer, and returns a JSON patch plus one question.

- **The page decides** the order of parts, when a part's clarifying questions
  are used up (four per part, six for the numbers), what a part still needs
  (computed from the file, never from the model), and what counts as ready.
- **The model decides** how to phrase the next question and which gap to ask
  about. Fourteen kinds of clarifying question are named in the prompt, among
  them: more than one decision, a word where a count belongs, a number without a
  range, a check with no error rate, an outcome not in money, two answers that
  disagree, and a spoken number that may have been misheard.
- **Nothing is invented.** The model files only what the expert said. A blank in
  a returned section never erases what was filed. Whatever a part still needs
  when the interview moves on becomes an open question in the document.

`src/core.js` holds all of this with no DOM, so the page and the tests run the
same code.

## Three ways to run it

| Where | Model | Voice | Saves to |
|---|---|---|---|
| The artifact link, inside claude.ai | the viewer's own Claude, with their consent | keyboard dictation only | the viewer's account when they may write, else their browser |
| `node serve.mjs`, then `http://localhost:8787` | the Claude Code CLI on this machine | the Speak button, live | `cases/<id>.json` on disk |
| Any other copy of the page | none | where the browser allows | the browser |

With no model the same thirteen parts run as a worksheet: the opening question
and one fixed checklist per part, and the answers are exported as written.

## Voice

The Speak button uses the browser's speech recognition (Chrome, Edge, Safari).
Words appear under the answer box as they are heard and move into the box when
the browser finalises them. Nothing is sent until the expert presses Send, and
a spoken answer is marked so the consultant confirms numbers that look misheard.

The claude.ai artifact viewer refuses microphone access to pages, so inside it
the button explains keyboard dictation instead (Mac: Fn twice; phones: the
keyboard microphone; Windows: Win+H). In-page voice together with a model
therefore needs the local server, or a hosted copy with its own model endpoint,
which does not exist yet (CC-O-01).

## Run and test

```sh
node build.mjs                      # dist/index.html (published) and dist/standalone.html
node serve.mjs                      # local page with voice; --port, --data, --model, --readback-model
node --test test/core.test.mjs      # 11 tests of the interview logic
node test/simulate.mjs              # a full interview against a simulated expert, about 15 minutes
node test/score.mjs test/simulated/sim-6xyy7b6n5l.json
```

Node 22, no dependencies. `serve.mjs` binds to 127.0.0.1 and rejects any other
Host header, because its endpoint spends the owner's model usage.

## What the simulated interview showed

`test/persona_equipment.md` scripts an expert (a buyer of used construction
equipment) holding 28 checkable facts, told to speak loosely until asked. The
consultant and the expert are both `claude-sonnet-5-5` at low effort; the
read-back is `claude-opus-5-5`. Both runs are in `test/simulated/`, scored by the
same script.

| | First run | After the fixes |
|---|---|---|
| Interview turns, unreadable replies | 27, 0 | 35, 0 |
| Scripted facts the expert stated | 23 of 28 | 25 of 28 |
| Of those, filed | 22 | 25 |
| Figures filed that the expert never said | 1 | 0 |
| Figures filed, without a range, without a source | 61, 38, 33 | 36, 10, 7 |
| Kinds of clarifying question used | 5 | 10 |

The first run is why parts 12 and 13 and the audit follow-ups exist; see
CC-D-01 to CC-D-03 in `docs/operations/incident_log.md`.

Not yet exercised: a real microphone, the model call inside the claude.ai
viewer, and a real expert. One scripted persona answering cooperatively is a
floor on difficulty, not a measurement of how the interview goes with people.
