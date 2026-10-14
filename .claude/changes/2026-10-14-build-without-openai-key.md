# Change: build the remaining stages before the OpenAI key is available

Date: 2026-10-14. Decided by: Takshit. Status: in effect until the key
arrives and the work listed under "What is owed" is done.

## What changes

plan.md has each stage prove itself before the next one starts. From
stage 5 on, some of those proofs need real answers from OpenAI, and
there is no API key yet.

The stages will be built anyway, in order, with the model and the
embeddings replaced in tests by scripted stand-ins. The proofs that need
a real model are postponed, not dropped. When the key arrives they are
run for every stage that is waiting on them.

Nothing in the design changes. The build order in plan.md stays the
same. What changes is that a stage can be finished in code while part of
its proof is still owed.

## Why this is possible

The model and the embeddings sit behind interfaces. Each has a real
implementation that calls OpenAI and a stand-in that does not:

- Embeddings: `Embedder` in `api/copilot/embeddings.py`, with
  `FakeEmbedder` (built in stage 4).
- The model: the same arrangement, to be built in stage 5.

CLAUDE.md already requires that no test calls OpenAI, so the tests are
written against the stand-ins in any case.

## What can and cannot be done without the key

| Stage | Done without the key | Owed until the key arrives |
|---|---|---|
| 4 Database and indexer (built) | Schema, indexer, keyword search | Search by meaning with real embeddings: "trailing stop" must return `ApplyStop` |
| 4b KB content | All of it | Nothing |
| 5 Write pipeline | Every step, the retries, the command, the eval runner | The 10 sample requests; the eval numbers; the exact API ids of the two models |
| 6 Review and Fix-from-error | Both modes. The checker's Verified findings are fully real | The AI-suggested findings; the rewritten code after "apply all fixes" |
| 7 API | All of it | Nothing new |
| 8 Website | All of it, showing scripted answers | A real Write and a real Review in the browser |
| 9 Deployment | The site can be put up | It cannot answer anyone until the key is set in production |

## The risk being accepted

The prompts cannot be tested against a stand-in, and they are the part
most likely to need rework. A scripted model returns exactly the JSON it
is told to return. A real one may write AFL that fails the checker more
often than expected, drop requirements, run into the limits of strict
JSON output, or take longer than the latency target.

Any of those can change the pipeline: how many attempts it makes, what
goes into the prompt, how much it retrieves. If that is found after
stages 6 to 8 are built on top of stage 5, some of that work is redone.

Until the owed proofs are run, "the tests pass" means the plumbing
works. It does not mean the product writes good AFL.

## How the risk is kept small

- The key is wanted by the end of stage 5, before stages 6 to 8 build on
  a pipeline that has only met a scripted model. Later is possible, at
  the cost described above.
- Every stage summary, and the stage's section in plan.md, says which
  parts have only been tested against a stand-in.
- CLAUDE.md's "Current state" keeps saying that nothing has been run
  with real OpenAI calls until that stops being true.
- No answer produced with a stand-in is ever shown as a real result,
  in an eval report or anywhere else.

## What is owed when the key arrives

In this order, since each depends on the one before:

1. Put `OPENAI_API_KEY` where the commands can read it, without it being
   committed.
2. List the account's models and put the exact ids for the strong and
   the cheap model in config. plan.md records "GPT-6.1 Sol" and "GPT-6
   Luna" as given; they are not confirmed.
3. Run `make index` with real embeddings, then search by meaning for
   "trailing stop" and confirm `ApplyStop` comes back (stage 4).
4. Run the 10 sample Write requests and the eval set; record the metrics
   from spec.md section 10 (stage 5).
5. Change the prompts and the pipeline as the results require, and
   update ARCHITECTURE.md if the design moved.
6. Run the Review samples with the real model and check the planted bugs
   are found and labelled (stage 6).
7. Do a full Write and a full Review in the browser (stage 8).

The cost of items 3 to 6 is expected to be a few dollars at most.

## When this record is closed

When every item above is done and plan.md shows no stage with a proof
still owed. Add the date and what the real runs changed to the end of
this file, and remove the "nothing has been run with real OpenAI calls"
note from CLAUDE.md.
