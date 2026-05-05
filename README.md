# Meadow Movie Inngest

An Inngest function that processes `movie.watched` events: fetches movie data from OMDb and sends a plot summary email via Resend.

## Quick start

```bash
# Option A: local (requires Python 3.11+)
make setup        # creates venv, installs deps, copies .env
# edit .env with your API keys
make dev          # starts FastAPI on :8000

# Option B: Docker
docker compose up # starts app + Inngest dev server

# Tests
make test
```

Then open the [Inngest Dev Server](http://localhost:8288) and send a test event, or:

```bash
curl -X POST http://localhost:8288/e/test \
  -H "Content-Type: application/json" \
  -d '{
    "name": "meadow_api/movie.watched",
    "data": {
      "movie_title": "The Matrix",
      "recipient_email": "peter@test.com"
    }
  }'
```

## How it works

```
meadow_api/movie.watched event
  │
  │  Pydantic validation (fail fast on bad input)
  │
  ├─ Step 1: fetch-movie-data     (OMDb API)
  │    Memoized on success, skipped on retry.
  │
  └─ Step 2: send-plot-email      (Resend API)
       Independent retry counter. Idempotency key via X-Entity-Ref-ID.
       │
       └─ on_failure: structured error logging
```

The two-step split is what makes this work. Inngest steps are the unit of durability: each one retries independently, and its return value is memoized. So if OMDb succeeds on the first attempt but Resend is temporarily down, retries go straight to the email step without re-fetching movie data. That's the main mechanism for "maximizing the chances of successfully sending the email." More detail in [ADR-001](DECISIONS.md).

## Design decisions

Full decision records are in [DECISIONS.md](DECISIONS.md). Here's the summary.

### Error classification matters more than retry count

I set `retries=10` (above the default 4), but the retry count isn't the interesting part. What matters is classifying which errors deserve retries at all:

| Error | Retry? | Why |
|-------|--------|-----|
| OMDb 5xx / timeout | Yes | Transient, backoff helps |
| OMDb 401 | No | Bad API key won't fix itself |
| OMDb "Movie not found" | No | Deterministic, title doesn't exist |
| OMDb "Plot: N/A" | No | Nothing to send |
| Resend rate limit / 5xx | Yes | Transient |
| Resend validation error | No | Bad email format |
| Resend invalid API key | No | Configuration issue |

Retrying a "movie not found" 10 times just delays the failure. `NonRetriableError` short-circuits these cases so the retry budget goes to errors that might actually resolve.

### Pydantic at the boundary, not inside steps

Event data is validated with a Pydantic model (`MovieWatchedEventData`) before any step runs. This catches structurally invalid emails and missing fields immediately. The model doubles as the event contract spec: a new developer can look at the schema file and know exactly what the function expects.

### Idempotency key for email delivery

If Resend accepts an email but the response gets lost (network partition), Inngest will retry the step and send a duplicate. I pass `X-Entity-Ref-ID: {run_id}-send-plot-email` as a deduplication signal. This isn't a hard guarantee since Resend will still send the duplicate, but email clients that respect the header will group them together, and it gives you a correlation key for debugging. A proper deduplication layer (check a database before sending) would be stronger but is out of scope here. More in [ADR-003](DECISIONS.md).

### on_failure handler

When all retries are exhausted, the failure handler logs structured context: movie title, recipient, run ID. In a real system this would feed into PagerDuty or a Slack channel so the team knows an email never went out.

## Assumptions

1. OMDb's `?t=` parameter does exact title matching. "Matrix" won't find "The Matrix." In production I'd fall back to `?s=` (search) and pick the top result.

2. The Resend sender domain is already verified. The `from` address assumes Meadow has set that up.

3. Plain text email is fine for now. An HTML template with poster, director, and rating would be a natural next step.

4. API keys come from environment variables, not the event payload.

## What I'd add with more time

- HTML email template with movie poster, year, director, and rating from the OMDb response.
- Integration test against the Inngest Dev Server with mocked external APIs to verify the full step orchestration.
- OMDb search fallback: try `?s=` when `?t=` returns nothing.
- Structured JSON logging for production log aggregation.

## Recommendation for improving this exercise

This exercise tests greenfield implementation, but most day-to-day engineering is modifying existing systems under constraints. An alternative that might be more revealing: provide a partially-implemented function with a subtle bug. For example, both API calls in a single function body with no step boundary, so OMDb gets re-fetched on every Resend retry. Ask candidates to find the problem and fix it. That tests debugging instinct and Inngest-specific understanding more directly than a blank-slate build, and it's closer to what the actual work looks like.
