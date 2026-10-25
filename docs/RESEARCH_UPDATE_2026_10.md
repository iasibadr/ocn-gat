# Research update — 25 October 2026

Author: Charadi Badr. This is a progress report, not a new product release.

## Scope and evidence availability

OCN remains an adaptation layer around an existing LLM agent. It changes access
selection, verified memory and bounded recovery; it does not train a foundation
model or modify its weights. GAT names the proposed integration tooling.

The four original experiments distributed in this repository remain reproducible
with their recorded-trace verifiers. The newer results below were checked against
local laboratory summaries and the SA-3 audit report. Their complete code,
protocols and inference traces are **not included in this documentation update**.
They are author-reported laboratory findings, not independently reproduced public
benchmarks. Do not use the original four verifiers to claim validation of SA-1–3.
The published executable core is unchanged.

## What was actually compared?

We assembled the agents, tools, tasks and perturbations ourselves using the
external smolagents framework and a local Qwen3.5:9b model. This was **not a test
of an independently developed agent application used unchanged**, nor a comparison
against ChatGPT or Claude products.

Within each pilot the arms use the same model, tools, permissions and budgets.
The simple control keeps access memory; matching is a stronger classical
assignment-based control; joint20 is the candidate OCN relational controller.
SA-1 used suggestions, while later pilots delegated bounded document access.
The documents and their movements are constructed, although LLM calls are real.
No personal agent or production service was used.

## Recorded pilot results

| Pilot | Simple control | Classical matching | OCN joint20 | LLM calls, simple / matching / OCN |
|---|---:|---:|---:|---:|
| SA-1 | 12/16 | 13/16 | 13/16 | 44 / 44 / 46 |
| SA-2 | 4/12 | 5/12 | 6/12 | 50 / 59 / 48 |
| SA-3 | 7/12 | 9/12 | 9/12 | 60 / 60 / 59 |

Each fraction counts successful missions per arm. Each pilot contains only two
independent trajectories; missions within a trajectory are correlated. The
pilots differ in tasks, seeds or interfaces, so their scores are not a causal
before/after estimate. All three failed their prospective superiority criterion.

### Latest pilot: SA-3

SA-3 ran 36 missions and 179 model calls with smolagents 1.26.0. Each mission
requires finding two reports, calculating their values and comparing them.
The budget is four document reads and at most seven model calls per mission.
There are eight sources with unique roles; role uniqueness is an assumption,
not an observed guarantee in arbitrary environments.

| Measure | Simple control | Matching | OCN |
|---|---:|---:|---:|
| Successful missions | 7/12 | 9/12 | 9/12 |
| Both reports found | 8/12 | 10/12 | 9/12 |
| Mission reads | 36 | 32 | 32 |
| Model calls | 60 | 60 | 59 |
| Cumulative mission time, seconds | 255.08 | 290.79 | 266.82 |

There are also 48 initial inventory reads across all arms and seeds. Mission
times exclude preparation, inventory and audit; they are not total deployment
costs. OCN's shorter measured time than matching in this run does not establish
a reproducible speed advantage. The required gain of two successes over the
best classical control was not reached.

The shared evidence interface now distinguishes requested and observed document
roles, exposes verified evidence, refreshes cached budget displays and validates
final answers, including framework fallback output. These safeguards are given
to every arm. Eight nonconforming outputs were rejected by the host; no
validation-triggered in-loop recovery was observed. Rejection is not evidence
of autonomous repair. Three other missions abstained and counted as failures.

The recorded audit passes for all 36 missions, checking controller replay,
provenance, budgets and comparative answers. Eight component tests were reported
passing. These checks are not an independent replication of the model calls.
No budget violation was observed in this constructed workload; this is not a
general security guarantee.

## What the theory has and has not contributed

- Quaternion experiments have not established an advantage over comparable
  real-valued or symbolic controls. In a constructed rotation test, the equivalent
  real matrix produced identical decisions. Quaternions are not used in SA-3.
- Multilayer feedback simulations explored admission, verification, memory,
  service load and recovery. Some gains were specific to combined stress;
  later variants did not meet their global promotion criteria. They are not
  evidence of superior real-agent performance.
- Dissipation, membranes and biological analogies guide hypotheses. Operational
  costs, information loss and physical heat must remain distinct; no measured
  thermodynamic law validates these pilots.
- Bounded relational memory remains worth testing, but the current assignment
  representation scales factorially (8! possibilities here). A general-purpose
  adaptive application is not yet available.

## Next falsifiable milestone

Select an existing open-source agent application with a verifiable document
task. Preserve its normal configuration as a control, then compare the same
application with OCN and with a strong classical recovery mechanism. Keep model,
tools, permissions, evidence checks and comparable resource budgets fixed.

Freeze success criteria before evaluation; use unseen disruptions, more
independent trajectories and full cost accounting. Measure supported task
completion, recovery without human repair, interventions, invalid answers and
budget violations. Publish a reviewed standalone reproduction package before
claiming public reproducibility or superiority for these newer pilots.

Adaptation is restricted to authorized actions. Escaping a sandbox or bypassing
permissions is a failure, not a successful adaptation. Universal recovery under
arbitrary perturbations is not a promise.

## Publication boundary

This update publishes only this report and documentation links. It does not
upload private laboratory history, raw conversations, credentials, infrastructure
configuration or personal-agent data. The existing MIT license and attribution
to Charadi Badr are retained.
