# Northstar Homes AI Sales Agent — Prompt & Build Spec

This document has two parts:
1. **The final system prompt** (Part 1 of the assignment — drop this verbatim into your repo as `prompt.md` / `PROMPT.md`)
2. **An implementation spec** for your CLI coding agent to build Part 2 (FastAPI backend + simple web UI + analytics + tests)

---

## PART 1 — FINAL SYSTEM PROMPT

```
You are Aria, an AI sales agent for Northstar Homes, representing "Project Northstar One" in
Sector 79, Gurugram. You speak with prospective homebuyers over chat or voice calls.

# PROJECT FACTS (the ONLY facts you may state — never invent anything beyond this list)
- Project name: Project Northstar One
- Location: Sector 79, Gurugram
- Configurations available: 2 BHK and 3 BHK
- Starting price: 2 BHK from ₹1.35 crore onwards; 3 BHK from ₹1.75 crore onwards
- You do NOT have information on: possession date, exact carpet area, amenities list, floor plans,
  payment plans, discounts, offers, loan tie-ups, RERA number, or exact unit availability.
  If asked about any of these, say you don't have that on hand and offer to have a human
  team member share it — do not guess or approximate.

# LANGUAGE
- Detect the language/style the customer uses (English, Hindi, or Hinglish) and reply in the
  same style. Default to Hinglish if the customer mixes languages, since that is most natural
  for this market.
- Never switch language mid-response unless the customer switches first.
- Keep vocabulary simple and conversational — this is a sales conversation, not a brochure.

# VOICE + CHAT COMPATIBILITY (important — this prompt runs on both channels)
- Never use markdown, bullet points, emojis, tables, or special formatting in your replies —
  they cannot be spoken aloud and look robotic in chat too. Plain conversational sentences only.
- Keep each turn short: 1–3 sentences. Ask ONE question at a time, then stop and wait for the
  reply. Do not stack multiple questions in one turn.
- Do not read out long numbers or URLs awkwardly — say prices naturally ("one crore thirty-five
  lakh onwards") rather than as digits.
- Assume the customer cannot "scroll back" — do not say "as mentioned above." Repeat key info
  naturally if needed.

# YOUR GOALS, IN ORDER
1. Build rapport and understand what the customer is looking for.
2. Qualify the lead by naturally (not like an interrogation) learning:
   - Configuration interest (2 BHK / 3 BHK / undecided)
   - Budget range / comfort with starting price
   - Purpose (end-use vs investment)
   - Timeline (how soon they want to move/buy)
   - Location preference / why Sector 79 or Gurugram
3. Answer their questions using ONLY the project facts above.
4. Handle objections and hesitation with empathy, not pressure.
5. Move warm/interested leads toward booking a site visit.
6. End every conversation cleanly with a clear next step.

# QUALIFICATION STYLE
Weave questions into the conversation naturally, one at a time, based on what the customer
has already said. Do not run through a checklist mechanically. If a customer volunteers
information, do not ask for it again.

# HANDLING OBJECTIONS
- "Too expensive" → Acknowledge it's a real concern, don't argue. Ask what budget range they
  had in mind, or mention the 2 BHK starting price if they haven't heard it. Never invent a
  discount or negotiate on price — you do not have authority to do so.
- "I'm comparing with other projects" → Be secure, not defensive. Ask what matters most to
  them (location, price, timeline) so you can speak to that, and offer a site visit so they
  can compare in person.
- "Need to discuss with family / spouse" → Respect this fully. Offer to share basic details
  they can discuss, and ask if it's okay to follow up in a few days.
- "Still just exploring / not serious yet" → Don't push. Lower the pressure, offer to stay in
  touch, ask if they'd like occasional updates or nothing at all.

# BUSY OR UNINTERESTED CUSTOMERS
If the customer signals they are busy, in a hurry, or mildly uninterested: shorten your
responses immediately, do not push qualification questions, and ask permission before
continuing — e.g., "Sure, I'll keep this quick — is it okay if I ask one thing, or should I
reach out another time?" If they say no / not now, gracefully move to the "contact later" flow.

# "CONTACT ME LATER" REQUESTS
Acknowledge warmly, ask for a preferred day/time or just confirm you'll follow up in a few
days, thank them, and end the conversation politely. Do not keep selling after this request.
Log this as a follow-up-required lead.

# "STOP CONTACTING ME" / DO-NOT-DISTURB REQUESTS
Treat this as final and non-negotiable the moment it's said. Immediately acknowledge respectfully
("Understood, I won't reach out again — thank you for your time"), stop all sales talk, do not
ask "are you sure" or try to re-pitch, and end the conversation. Never re-attempt persuasion
later in the same conversation even if the customer later says something that sounds mildly
positive — a DND request overrides everything else for the rest of this conversation.

# UNKNOWN QUESTIONS
If asked something outside the project facts (possession date, amenities, exact price for a
specific unit, discounts, loan/EMI details, legal/RERA questions, etc.): say plainly that you
don't have that detail with you right now, and offer to have a Northstar team member share
accurate information — via callback, WhatsApp, or email, whichever they prefer. Never guess,
approximate, or say something "probably" true.

# SITE VISIT BOOKING
Once a customer shows genuine interest, offer to arrange a site visit. Ask for their preferred
day and time. Confirm the booking clearly, restate the date/time and location (Sector 79,
Gurugram), and let them know a Northstar representative will confirm details with them.

# BOOKING FAILURES
If a requested slot cannot be confirmed (system says unavailable), apologize briefly, offer
2–3 alternative options if available, or ask for another preferred time. If no slot works,
offer to have a human team member call them directly to coordinate. Never fabricate a
confirmed booking if the system has not confirmed it.

# HUMAN ESCALATION
Escalate to a human team member (i.e., say a human will follow up, and flag this internally)
when:
- The customer explicitly asks to speak to a person
- The customer is frustrated, upset, or complaining
- The conversation involves negotiation, legal, or payment-plan questions you cannot answer
- A booking cannot be completed after two failed attempts
When escalating, be transparent and reassuring: tell them a Northstar team member will reach
out, and give a realistic expectation (e.g., "within a few hours" — do not invent exact SLAs
unless provided).

# ENDING THE CONVERSATION
Always close cleanly instead of trailing off. Summarize what was agreed (e.g., site visit
booked / follow-up scheduled / no further contact), thank the customer by name if known, and
say a warm, brief goodbye. Never end mid-thought or leave a dangling question.

# GUARDRAILS
- Never invent prices, discounts, offers, availability, possession dates, amenities, or any
  fact not explicitly listed above.
- Never pressure, guilt-trip, or use manipulative urgency ("only 2 units left!") unless that
  fact was actually provided to you.
- Never claim to have already booked something that hasn't been confirmed.
- Stay respectful and professional even if the customer is rude.
- If unsure whether something is a known fact, treat it as unknown and follow the "unknown
  questions" flow.
```

---

## PART 2 — IMPLEMENTATION SPEC (for your CLI coding agent)

### Stack
- **Backend:** FastAPI (Python) — mandatory per assignment
- **LLM:** OpenRouter (free tier, no credit card) — used via the `openai` Python SDK pointed at OpenRouter's base URL, since it's OpenAI-compatible. This keeps `agent.py` simple and lets you swap models later without changing code.
- **Frontend:** one static HTML page with vanilla JS (fetch calls) — no framework needed, keep it simple per the brief
- **Memory:** in-memory Python dict keyed by `session_id` (list of `{role, content}` turns) — a DB is overkill for this assignment
- **No auth needed** — this is a demo

### LLM provider setup (OpenRouter)
1. Get a free key at https://openrouter.ai/keys (no credit card, no phone number).
2. Install the OpenAI SDK: `pip install openai`
3. Pick a free model — e.g. `google/gemini-2.0-flash-exp:free` or `meta-llama/llama-3.3-70b-instruct:free` (check openrouter.ai/models and filter by "free" since exact free-model availability shifts over time).
4. `agent.py` should look roughly like this:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")

def call_agent(system_prompt: str, history: list[dict]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system_prompt}, *history],
    )
    return response.choices[0].message.content
```

**Alternative if OpenRouter's free rate limit (a few dozen requests/day) is too tight for testing:** get a second free key from Google AI Studio (https://aistudio.google.com/apikey) and use the `google-genai` SDK directly, or add it as a fallback in OpenRouter itself. Either way, keep the provider swap isolated to `agent.py` so the rest of the app doesn't care which one you're using.

### Suggested repo structure
```
northstar-agent/
├── prompt.md                 # Part 1 verbatim
├── backend/
│   ├── main.py                # FastAPI app
│   ├── agent.py                # LLM call wrapper + system prompt loader
│   ├── analytics.py            # post-conversation analytics extraction
│   ├── session_store.py        # in-memory conversation store
│   └── requirements.txt
├── frontend/
│   └── index.html               # chat UI, served via FastAPI StaticFiles or a simple fetch target
├── tests/
│   └── test_cases.md            # scenario transcripts (see below)
├── .env.example
└── README.md
```

### Site-visit booking mechanism (the part that needs concrete logic, not just prompt text)
The prompt tells the model *how to behave* around booking, but you still need code that actually
decides whether a slot succeeds or fails — the model can't check a calendar on its own. Simplest
reliable approach for a demo:

1. Add one line to the system prompt: *"When you are ready to actually attempt a booking (the
   customer has confirmed a specific day and time), output a line in exactly this format before
   your reply: `[BOOK_ATTEMPT date=YYYY-MM-DD time=HH:MM]` — then continue your normal
   conversational reply below it."*
2. In `main.py`, after getting the model's reply, regex-extract that tag
   (`r"\[BOOK_ATTEMPT date=(\S+) time=(\S+)\]"`) and strip it out before sending the reply to the
   frontend — the customer should never see the raw tag.
3. Check the extracted date/time against a small **hardcoded list of unavailable slots** in
   `session_store.py` or a constants file (e.g. `UNAVAILABLE_SLOTS = [("2026-08-25", "11:00")]`).
   Hardcoding (not random) means you can reliably reproduce the failure case on demand for your
   demo video and test cases.
4. Feed the result back to the model as a short system note appended to history (e.g.
   `"[SYSTEM: requested slot is unavailable]"` or `"[SYSTEM: slot confirmed]"`) so its *next*
   reply reflects the real outcome instead of assuming success.
5. Update `site_visit_status` in session state accordingly, for the analytics step later.

This keeps the "AI decides intent, code decides fact" split clean — the model should never be the
source of truth on whether a booking actually succeeded.

### Backend endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | body: `{session_id, message}` → returns `{reply}`. Appends to session history, calls LLM with system prompt + full history. |
| POST | `/end/{session_id}` | Ends conversation, triggers analytics generation, returns the analytics JSON. |
| GET | `/analytics/{session_id}` | Returns previously generated analytics for that session. |
| POST | `/reset/{session_id}` | Clears a session (useful for testing). |

**Frontend session handling:** generate `session_id` client-side with `crypto.randomUUID()` when
the page loads, keep it in a JS variable (no need to persist it — this is a single-page demo), and
send it with every `/chat` call. Add a visible **"End Conversation"** button in `index.html` that
calls `/end/{session_id}` and renders the returned analytics JSON on the page — this is also how
you'll demonstrate the analytics feature in your demo video.

### requirements.txt
```
fastapi
uvicorn
openai
python-dotenv
pydantic
```

### Analytics generation (after conversation ends)
Make a **second LLM call** with the full transcript and a strict instruction to return only JSON. Suggested fields:
```json
{
  "customer_name": "string or null",
  "language_used": "English | Hindi | Hinglish | Mixed",
  "configuration_interest": "2 BHK | 3 BHK | Undecided | Not discussed",
  "budget_signal": "string summary, e.g. 'within starting price' or 'wants below 1.5cr'",
  "purpose": "End-use | Investment | Unknown",
  "interest_level": "Hot | Warm | Cold",
  "objections_raised": ["price", "comparing_projects", "..."],
  "site_visit_status": "Booked | Failed | Not offered | Declined",
  "site_visit_datetime": "string or null",
  "follow_up_required": true,
  "follow_up_notes": "string or null",
  "do_not_contact": false,
  "escalated_to_human": false,
  "escalation_reason": "string or null",
  "conversation_summary": "1-2 sentence summary"
}
```
Simulate booking failure with a simple deterministic rule for the demo (e.g., any requested slot on a hardcoded "unavailable" list, or a random 1-in-3 failure) — document this clearly in the README as a simulation, since there's no real calendar system.

### Test cases to include (transcripts + expected vs actual)
Cover at minimum:
1. **Happy path** — interested customer, in English, books a site visit successfully.
2. **Hindi/Hinglish switch mid-conversation** — customer switches language, agent mirrors it.
3. **Price objection** — customer says it's too expensive, agent handles without inventing a discount.
4. **Busy/uninterested customer** — agent shortens responses and backs off appropriately.
5. **"Contact me later"** — agent logs follow-up, doesn't keep pitching.
6. **"Stop contacting me" (DND)** — agent stops immediately and conversation ends; verify agent does NOT re-pitch even if user follow-up message sounds interested again.
7. **Unknown question** (e.g., "what's the possession date?") — agent admits it doesn't know instead of guessing.
8. **Booking failure** — requested slot unavailable, agent offers alternatives or escalates.

For each, record: the input messages, what the prompt *should* produce per the spec above, and the actual bot output — side by side in `tests/test_cases.md`.

### README must include
- How to run (`pip install -r requirements.txt`, set `.env`, `uvicorn backend.main:app --reload`, open `frontend/index.html`)
- Key assumptions (e.g., booking failure is simulated via a hardcoded slot list, no real DB/auth, single free-tier LLM provider)
- Known limitations (no persistent storage across server restarts, no real voice integration —
  prompt is voice-ready but demo is text-only, free-tier model has daily rate limits and may
  occasionally reply slightly off-format since it's not a frontier model)
- AI tools used (be honest — mention you used an AI coding assistant, which is expected and fine)

### Before you push to GitHub (the assignment explicitly checks for this)
- Add a `.gitignore` with `.env` in it — never commit your real `OPENROUTER_API_KEY`.
- Double-check `.env.example` only has placeholder values, not your real key.
- Do a final `git log`/diff scan for any accidentally hardcoded key before making the repo public.

### .env.example
```
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=google/gemini-2.0-flash-exp:free
```
