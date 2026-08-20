# Northstar One — AI Sales Agent (Huvo AI Assignment)

An AI conversational sales agent for **Northstar Homes** (fictional real-estate company) selling
**Project Northstar One**, Sector 79, Gurugram. Built for the Huvo AI Forward Deployed Engineer
assignment: a single system prompt designed for **both chat and voice** interactions, wrapped in
a minimal FastAPI app with a web chat UI, simulated site-visit booking, and post-conversation
analytics.

## Quick start

```bash
# 1. Clone / enter the repo
cd northstar-agent

# 2. Create venv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 3. Configure the LLM provider (free tier)
cp .env.example .env
#   - Get a free key at https://openrouter.ai/keys (no credit card)
#   - Edit .env and put your key in OPENROUTER_API_KEY

# 4. Run the server
uvicorn backend.main:app --reload
```

Open **http://localhost:8000** — the chat UI is served by FastAPI itself (no CORS issues, no
separate static server).

> **No API key?** The app still runs: `/chat` and `/end` return graceful fallback replies and
> session-fact-based analytics instead of crashing. Add a key to get real agent behaviour.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | Body `{session_id, message}` → `{reply}`. Keeps per-session history. |
| POST | `/end/{session_id}` | Ends the conversation, generates analytics JSON. |
| GET | `/analytics/{session_id}` | Returns analytics for an ended session. |
| POST | `/reset/{session_id}` | Clears a session (for testing). |
| GET | `/` | Chat UI. |

The UI generates a `session_id` with `crypto.randomUUID()` on page load; the **End Conversation**
button calls `/end` and renders the analytics JSON on the page.

## How it works

- **Prompt** (`prompt.md`): the final system prompt. Voice-ready (no markdown, 1–3 sentence
  turns, one question at a time, natural price phrasing, STT-typo tolerance) and chat-ready.
  Handles qualification, English/Hindi/Hinglish mirroring, objections, busy/uninterested
  customers, "contact later", DND, unknown questions, booking, booking failures, human
  escalation, clean endings, and prompt-injection resistance.
- **Booking is code-verified, not model-verified**: when the customer confirms a specific slot,
  the prompt instructs the model to emit `[BOOK_ATTEMPT date=YYYY-MM-DD time=HH:MM]`. `main.py`
  extracts the tag, checks the (simulated) calendar, and re-prompts the model with the real
  outcome — the model never decides whether a booking succeeded.
- **Memory**: in-memory dict keyed by `session_id` (no DB — demo scope). Idle sessions are
  cleaned up after 1 hour.
- **Analytics**: a second LLM call turns the transcript into a strict JSON report (with a
  regex fallback if the model returns non-JSON). Session facts from the booking system
  (`site_visit_status`, `escalated_to_human`, `do_not_contact`, …) always override the model,
  so analytics can't contradict what the code recorded.

## Key assumptions

- **Booking simulation**: any slot at **11:00** fails; past slots fail; everything else
  succeeds. No real calendar — documented as a simulation.
- **LLM provider**: OpenRouter free tier (`openrouter/free` routes to a random free model).
  ~20 req/min and 50 req/day. Swap `OPENROUTER_MODEL` in `.env` to pin a specific model
  (e.g. `google/gemma-4-31b-it:free`).
- No real DB, no auth, no persistent storage across restarts — this is a demo.
- IST timezone assumed for booking-date validation.

## Known limitations

- In-memory sessions are lost on server restart.
- No real voice integration — the prompt is voice-ready, but the demo is text-only.
- Free-tier models have tight rate limits and occasionally reply slightly off-format; the
  booking tag and analytics JSON both have code-level fallbacks for this.
- **OpenRouter free tier caps at 50 requests/day** (`free-models-per-day`). When the quota is
  exhausted the agent enters degraded mode: it explains honestly that its language service is
  unavailable, notes the customer's message for a Northstar representative, breaks the
  "technical snag" loop (a rep request gets a definitive handoff), and a 30-second circuit
  breaker stops hammering the API. Booking state and captured contact details remain intact,
  and analytics still produce a full heuristic report without the LLM.
- `openrouter/free` picks models at random, so tone may vary slightly between sessions.
- Analytics uses a best-effort second LLM call; if it fails, a heuristic report built from
  session facts and the transcript is returned instead.

## Test cases

- **`tests/test_backend.py`** — automated pytest suite (23 tests) covering slot validation, session
  store, all HTTP endpoints, booking success/failure/escalation flows, and fallbacks. Run with
  `.venv/bin/python -m pytest tests/` (adds `pytest` + `httpx` to `backend/requirements.txt`).
- **`tests/test_cases.md`** — 10 manual live-run scenarios (happy path, Hinglish, price objection,
  busy customer, contact-later, DND, unknown question, booking failure, escalation, prompt
  injection) with expected behaviour and placeholders for live transcripts.

## Project structure

```
northstar-agent/
├── prompt.md                 # Final system prompt (Part 1 deliverable)
├── backend/
│   ├── main.py               # FastAPI app + booking tag processing
│   ├── agent.py              # OpenRouter client + date-injected prompt
│   ├── analytics.py          # Post-conversation analytics extraction
│   ├── session_store.py      # In-memory sessions + idle cleanup
│   ├── constants.py          # Unavailable slots + booking helpers
│   └── requirements.txt
├── frontend/
│   └── index.html            # Chat UI (served by FastAPI)
├── tests/
│   ├── test_backend.py         # Automated pytest suite (23 tests)
│   └── test_cases.md           # Manual scenario transcripts (input / expected / actual)
├── .env.example
├── .gitignore
└── README.md
```

## AI tools used

- **Claude (opencode CLI)** — used to draft the system prompt, write the FastAPI backend, UI,
  and this README. All generated code was reviewed and verified locally before submission.
- **OpenRouter** — free-tier LLM API used for agent responses.