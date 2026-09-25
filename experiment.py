"""Jev inbox-triage experiment.

Sends 60 hand-labelled customer messages to TypeSafe's Jev decision model in
parallel, then measures speed, cost, accuracy, and how accuracy changes when
you only automate the answers Jev is confident about.

Run:  TYPESAFE_API_KEY=... python experiment.py
"""
import asyncio
import json
import time

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, Score

from inbox import INBOX

PRICE_PER_M_INPUT = 0.042  # USD, output tokens are free

QUESTIONS = {
    "team": Choice(
        instructions="Which team at a software company should handle this incoming message?",
        criteria={
            "billing": "Invoices, charges, refunds, payment methods, prices on an existing bill",
            "technical": "Bugs, outages, errors, how-to questions about using the product",
            "sales": "New purchases, plans, quotes, discounts, upgrades, compliance questions from buyers",
            "cancellation": "The customer wants to cancel, pause, downgrade, delete their account or stop paying",
            "spam": "Unsolicited marketing, scams, phishing, cold outreach unrelated to being a customer",
        },
    ),
    "churn": Noul(instructions="The sender is at real risk of leaving or downgrading as a customer."),
    "urgency": Score(
        instructions="How urgently does this message need a human reply?",
        criteria=[
            "Can wait a week",
            "Reply within a few days",
            "Reply today",
            "Reply within the hour, the customer is upset or blocked",
        ],
    ),
}


async def classify(client, sem, i, text):
    async with sem:
        t0 = time.perf_counter()
        r = await client.system_one({"message": text}, QUESTIONS)
        ms = (time.perf_counter() - t0) * 1000
    team = r.choices["team"]
    return {
        "id": i,
        "latency_ms": round(ms, 1),
        "team": team.choice,
        "team_confidence": team.confidence,
        "team_probs": dict(team.probabilities),
        "churn": r.nouls["churn"].noul,
        "urgency": r.scores["urgency"].score,
        "input_tokens": r.usage.input_tokens,
        "model": r.model,
    }


async def main():
    sem = asyncio.Semaphore(20)
    retry = RetryPolicy(max_retries=3, backoff_initial=0.5)
    async with AsyncTypeSafeClient(retry=retry) as client:
        # warm-up call so connection setup isn't counted
        await client.system_one({"message": "hello"}, {"x": Noul(instructions="This is a greeting.")})
        t0 = time.perf_counter()
        preds = await asyncio.gather(*(classify(client, sem, i, m[0]) for i, m in enumerate(INBOX)))
        wall = time.perf_counter() - t0

    rows = []
    for (text, team, churn), p in zip(INBOX, preds):
        rows.append({"text": text, "true_team": team, "true_churn": churn, **p,
                     "team_correct": p["team"] == team,
                     "churn_correct": (p["churn"] >= 0.5) == churn})

    n = len(rows)
    tokens = sum(r["input_tokens"] for r in rows)
    lat = sorted(r["latency_ms"] for r in rows)

    # confidence gate: automate only when team_confidence >= t
    gates = []
    for t in [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9]:
        auto = [r for r in rows if r["team_confidence"] >= t]
        gates.append({"threshold": t, "automated_pct": len(auto) / n * 100,
                      "accuracy_pct": (sum(r["team_correct"] for r in auto) / len(auto) * 100) if auto else None})

    summary = {
        "model": rows[0]["model"],
        "messages": n,
        "questions_per_message": len(QUESTIONS),
        "wall_seconds": round(wall, 2),
        "median_latency_ms": lat[n // 2],
        "p95_latency_ms": lat[int(n * 0.95) - 1],
        "input_tokens": tokens,
        "cost_usd": tokens / 1e6 * PRICE_PER_M_INPUT,
        "team_accuracy_pct": sum(r["team_correct"] for r in rows) / n * 100,
        "churn_accuracy_pct": sum(r["churn_correct"] for r in rows) / n * 100,
        "gates": gates,
    }
    json.dump({"summary": summary, "rows": rows}, open("results.json", "w"), indent=2)
    print(json.dumps(summary, indent=2))
    print("\nMisses:")
    for r in rows:
        if not r["team_correct"]:
            print(f"  [{r['team_confidence']:.2f}] true={r['true_team']:<12} got={r['team']:<12} {r['text'][:70]}")


if __name__ == "__main__":
    asyncio.run(main())
