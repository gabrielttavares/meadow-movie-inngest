# Decision records

These cover choices that aren't obvious from reading the code.

---

## ADR-001: Two durable steps instead of one function body

The function calls OMDb then Resend. I could have put both calls in a single function body, but I split them into two `step.run()` calls instead.

Each Inngest step retries independently and its return value is memoized. If OMDb succeeds on the first attempt but Resend is temporarily down, subsequent retries skip OMDb entirely and go straight to the email. We don't re-fetch data we already have, and we don't burn retry attempts on a step that already worked. That's how the function "maximizes the chances of successfully sending the email," as the prompt asks for.

The trade-off is two HTTP round-trips to the Inngest server for step state persistence instead of one. For a two-step function, this is negligible. If the function had 20+ steps, I'd start thinking about batching or reducing step boundaries.

---

## ADR-002: Retry budget of 10 with NonRetriableError classification

Inngest defaults to 4 retries. The prompt says to maximize delivery success, so I raised it to 10.

But the retry count alone isn't what matters. More retries just means a wider time window for transient failures to resolve (Inngest uses exponential backoff). That's only useful if the failure is actually transient. A "movie not found" from OMDb will fail identically every time. Retrying it 10 times just adds delay before you find out.

So the real work is in classifying errors:
- Retriable: HTTP 5xx, timeouts, rate limits. These are transient by nature.
- Non-retriable: 401 (bad API key), movie not found, invalid email, missing event fields. These are deterministic. `NonRetriableError` short-circuits them immediately.

---

## ADR-003: Idempotency via X-Entity-Ref-ID header

If Resend accepts an email but the response gets lost (network partition), Inngest will retry the step and send a duplicate. For a "movie plot summary" email, a duplicate is annoying but not catastrophic. For other event types it could be worse.

I pass `X-Entity-Ref-ID: {run_id}-send-plot-email` as a header on the Resend call. This is the standard email header for deduplication. It won't stop Resend from sending the duplicate, but email clients that respect it will group them together, and it gives you a correlation key when debugging.

A stronger guarantee would mean checking a database before sending (did we already send for this run_id?). That's out of scope for a 2-hour exercise. Resend didn't expose a first-class idempotency parameter when I checked, so the header approach is what's available.

---

## ADR-004: Pydantic model for event validation instead of manual checks

The event payload needs validation: is `movie_title` present? Is `recipient_email` actually an email? I could do this with `if not event_data.get("movie_title")` checks, but I went with a Pydantic model instead.

Manual checks only verify presence. `EmailStr` catches structurally invalid emails before we ever hit the Resend API. The model also makes the event contract explicit: a new developer can open the schema file and see exactly what the function expects without reading through the handler logic.

The trade-off is adding `pydantic[email]` as an explicit dependency, though Pydantic is already pulled in by FastAPI anyway. Validation runs before any step executes, so invalid events fail fast without touching external APIs.
