# Jev inbox triage

Can a *decision model* run a customer support inbox?

[Jev](https://docs.typesafe.ai/introduction) (TypeSafe AI, Sept 2026) doesn't write text. You give it some state and typed
questions, and it returns a choice, a yes/no probability or a score, each with a confidence value.
This repo tests it on 60 realistic, hand-labelled emails to a fictional software company.

For every email Jev answers three questions in one call:

| Question | Type | Output |
| --- | --- | --- |
| Which team should handle it? | `Choice` | billing / technical / sales / cancellation / spam |
| Is the sender at risk of leaving? | `Noul` | probability 0–1 |
| How fast does it need a reply? | `Score` | 0 (can wait a week) to 3 (within the hour) |

## Results

Run on 25 Sept 2026 via Vercel AI Gateway (`typesafe-ai/jev`). Full output in [`results.json`](results.json).

| | |
| --- | --- |
| Routed to the right team | **56 / 60 (93%)** |
| Median latency per email (3 questions) | **338 ms** (p95 714 ms) |
| Input tokens | 32,120 |
| Cost | **$0.0013** (≈ $0.23 per 10,000 emails) |
| Churn-risk flag correct | 56 / 60 (93%) |
| Hidden churn caught (at risk, but not a cancellation email) | **8 / 8** |

### Confidence is the useful part

| Only automate when confidence ≥ | Share of inbox automated | Accuracy on those |
| --- | --- | --- |
| 0.0 | 100% | 93.3% |
| 0.6 | 93.3% | 98.2% |
| 0.9 | 86.7% | 98.1% |

Three of the four mistakes had confidence below 0.6, and they were genuinely ambiguous emails
("If you can't fix the export bug this week, please just cancel us."). The one confident miss was
"Do you accept purchase orders?", which I labelled billing and Jev called sales.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# with a TypeSafe key
TYPESAFE_API_KEY=... .venv/bin/python experiment.py

# or through Vercel AI Gateway
AI_GATEWAY_API_KEY=... CONCURRENCY=2 .venv/bin/python experiment.py
```

Answers are cached in `cache.json` as they arrive, so if the API rate-limits you, run it again and it resumes.
Edit [`inbox.py`](inbox.py) to try your own messages.

## Carousel

[`carousel/carousel.html`](carousel/carousel.html) is the LinkedIn carousel built from these results.
To regenerate the PDF (macOS, uses the built-in WebKit):

```bash
python3 -m http.server 8765 --directory carousel &
swift tools/export_pdf.swift "http://localhost:8765/carousel.html#export" carousel/jev-inbox-test.pdf
```

## Caveats

- 60 emails is a small sample, and I wrote and labelled them myself.
- Latency was measured on the last day of Vercel's free Jev promo, with the gateway under heavy load.
- Jev's answers are not fully deterministic, so a rerun can shift individual confidences.
