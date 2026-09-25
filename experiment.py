"""Jev inbox-triage experiment.

Sends 60 hand-labelled customer messages to TypeSafe's Jev decision model in
parallel, then measures speed, cost, accuracy, and how accuracy changes when
you only automate the answers Jev is confident about.

Run with a TypeSafe key:          TYPESAFE_API_KEY=... python experiment.py
or through Vercel's AI Gateway:   AI_GATEWAY_API_KEY=... python experiment.py
"""
import asyncio
import json
import os
import time

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, Score, TypeSafeRateLimitError

from inbox import INBOX

PRICE_PER_M_INPUT = 0.042  # USD, output tokens are free
CACHE = "cache.json"  # answers saved as they arrive, so a rerun resumes

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
    # Retry 429s ourselves so latency_ms only measures the call that succeeded.
    async with sem:
        for attempt in range(12):
            try:
                t0 = time.perf_counter()
                r = await client.system_one({"message": text}, QUESTIONS)
                ms = (time.perf_counter() - t0) * 1000
                break
            except TypeSafeRateLimitError:
                wait = min(2 ** attempt, 60)
                print(f"  #{i}: rate limited, retrying in {wait}s")
                await asyncio.sleep(wait)
        else:
            print(f"  #{i}: gave up, rerun to resume")
            return None
    team = r.choices["team"]
    print(f"  #{i}: {team.choice} ({ms:.0f} ms)")
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


def client_kwargs():
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY")
    if gateway_key:
        return {"api_key": gateway_key, "base_url": "https://ai-gateway.vercel.sh/typesafe",
                "model": "typesafe-ai/jev"}
    return {}


async def main():
    sem = asyncio.Semaphore(int(os.environ.get("CONCURRENCY", 20)))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [i for i in range(len(INBOX)) if str(i) not in cache]
    print(f"{len(cache)} cached, {len(todo)} to go")

    async def run(client, i):
        p = await classify(client, sem, i, INBOX[i][0])
        if p:
            cache[str(i)] = p
            json.dump(cache, open(CACHE, "w"), indent=2)

    async with AsyncTypeSafeClient(retry=RetryPolicy(max_retries=0), **client_kwargs()) as client:
        t0 = time.perf_counter()
        await asyncio.gather(*(run(client, i) for i in todo))
        wall = time.perf_counter() - t0

    if len(cache) < len(INBOX):
        print(f"\n{len(INBOX) - len(cache)} messages still missing, run again to finish.")
        return
    preds = [cache[str(i)] for i in range(len(INBOX))]

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
        "wall_seconds_last_run": round(wall, 2),
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
