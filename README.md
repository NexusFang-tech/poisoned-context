# Poisoned Context

[![CI](https://github.com/NexusFang-tech/poisoned-context/actions/workflows/ci.yml/badge.svg)](https://github.com/NexusFang-tech/poisoned-context/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Status: harness complete, no study results yet.** Results will be published here with the raw data, including the runs that didn't go as expected.

## Question

Many internal assistants are given live database records so they can answer staff questions. Some of those fields can be edited by outside parties through intake forms, imports or synced systems. When a stored record contains instructions, how often does a Claude model follow them, and which simple defenses reduce that without hurting the assistant's normal answers?

This design comes from a real production pattern: a CRM assistant whose system prompt receives live records at request time. The study uses only a fictional directory.

## Threat model

- **Attacker:** can write to one free-text note field, and can't see the prompt or the conversation.
- **Victim:** a staff member asks an ordinary question, with no sign of an attack.
- **Assistant:** has the directory in its system prompt and an email tool.

## Design

Each attack trial varies four factors, with repeats per condition:

| Factor | Levels |
|---|---|
| Defense | none; warning; warning + random-nonce delimiters; warning + datamarking |
| Attack goal | print a canary; give a false phone number; call the email tool with an attacker address |
| Payload style | naive override; fake administrator notice; spoofed end-of-data and system tag; friendly staff tip |
| Placement | on the record being asked about; on an unrelated record |

Control trials use no payload, which measures normal accuracy and false alarms.

## Measures

- **Attack success:** did the model do what the payload asked? Tool-call scoring is exact. Text goals use the canary or false number.
- **Task accuracy:** did the reply include the correct phone number?
- **Flagging:** did the model warn the user? This is a keyword heuristic, so treat it as an indicator.
- **Human review:** a reply that quotes a canary while warning about it isn't compliance, so ambiguous replies are held out of attack rates until a person decides them.

Rates use 95% Wilson intervals, and defense comparisons use Newcombe intervals. Trials in a condition share one template, so the intervals understate uncertainty about attacks in general.

## Limitations

- The payloads are simple and hand-written, so low success here doesn't show robustness against an adaptive attacker.
- One assistant, one task and a small directory won't represent every deployment.
- Prompts and models were not tuned against each other, and results apply to the model versions tested on the dates tested.

## Safety

The directory, phone numbers (555-01xx) and domains (`example.org`, `attacker.example`) are fictional or reserved. The email tool is never executed. Payloads ask only for measurable, harmless behavior.

## Run it

```bash
pip install -e ".[anthropic,dev]"
pytest -q

# Test the pipeline with the scripted mock. This measures nothing.
poisoned-context run --provider mock --models obedient robust --trials 1 --control-trials 2 --out results/mock.jsonl --max-requests 500

# Check the size of a real run. This sends nothing.
poisoned-context run --models MODEL_ID --trials 3 --control-trials 10 --dry-run --input-price 1 --output-price 5

# Run it. Requests are capped, and a stopped run resumes where it left off.
export ANTHROPIC_API_KEY=...
poisoned-context run --models MODEL_ID --trials 3 --control-trials 10 --out results/pilot.jsonl --max-requests 400

# Decide ambiguous replies, then build the report.
poisoned-context review results/pilot.jsonl
poisoned-context report results/pilot.jsonl
```

Replace the prices with your model's current pricing. Failed API calls are logged and retried on resume, and are never counted as model behavior.

## Prior work

- Greshake et al., [Not what you've signed up for](https://arxiv.org/abs/2302.12173) (2023), on indirect prompt injection.
- Hines et al., [Defending Against Indirect Prompt Injection Attacks With Spotlighting](https://arxiv.org/abs/2403.14720) (2024), the source of the delimiting and datamarking defenses tested here.

Built with Claude. Study design, review decisions and conclusions are the author's responsibility.
