"""
Advanced text summarizer routes.
Summarizes pasted text or the current transcript with an OpenAI-compatible model.
"""

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

try:
    from ..auth import require_authenticated_request
    from ..config import config
except ImportError:
    from auth import require_authenticated_request
    from config import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/text-summarizer", tags=["text-summarizer"])


class SummarizerMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=12000)


class SummarizerRequest(BaseModel):
    text: str = Field(default="", max_length=260000)
    instruction: str = Field(default="", max_length=4000)
    mode: str = Field(default="professional")
    title: str = Field(default="", max_length=180)
    history: list[SummarizerMessage] = Field(default_factory=list)


SYSTEM_PROMPT = """You are a senior executive summarization assistant.

You can summarize meeting transcripts, business notes, emails, reports, technical plans, and pasted text.

Rules:
1. Preserve facts, numbers, names, dates, decisions, owners, deadlines, and uncertainty exactly.
2. Do not invent details. If something is not present, write "Not mentioned".
3. Make the output professional, structured, readable, and useful for leadership review.
4. Separate what happened, why it matters, decisions, action items, risks, and next steps.
5. For messy transcripts, infer the conversation flow only from the supplied text.
6. If the user asks a direct question, answer it using only the supplied text and conversation context.
7. Make the answer easy to scan: short sections, strong headings, concise bullets, and only a small number of useful tables.
8. Do not produce a wall of text. Prefer 4-7 focused sections over many tiny fragments.
9. Do not put everything in tables. Use bullets or short paragraphs for context, discussion flow, key takeaways, explanations, risks, and next steps.
10. Use Markdown tables only when the information has repeated fields, such as task tracking, decisions with owners/dates, status lists, metrics, comparisons, or issue trackers.
11. If a section has fewer than 3 structured rows, prefer bullets instead of a table unless it is To-do tasks mode.
12. For any task table, use these columns unless the user asks otherwise: Priority | Task | Owner | Deadline | Status | Dependency / Blocker.
"""


MODE_GUIDANCE = {
    "professional": (
        "Create a polished professional summary. Use this structure: Executive Snapshot, Context, Key Takeaways, "
        "Decisions / Agreements, Action Items, Risks / Concerns, Next Steps. Use bullets for most sections. "
        "Use a table only for Action Items or Decisions when there are multiple concrete rows with owner/date/status fields."
    ),
    "executive": (
        "Create a concise executive brief for leadership. Use this structure: Bottom Line, Business Impact, "
        "Important Updates, Decisions Needed, Risks, Recommended Next Moves. Prefer bullets. Use one compact table "
        "only if several decisions, owners, dates, or statuses must be compared."
    ),
    "meeting": (
        "Create meeting minutes. Use this structure: Meeting Context, Discussion Summary, Decisions, "
        "Action Items, Open Questions, Follow-up Plan. Use bullets for discussion and open questions. "
        "Use tables only for Action Items or Decisions when they contain repeated owner/deadline/status fields."
    ),
    "actions": (
        "Extract only operational information. Use a table for Action Items when there are multiple tasks. "
        "Use bullets for blockers, dependencies, decisions, and follow-up questions unless they clearly need columns."
    ),
    "todo": (
        "Create a practical to-do task plan. Start with a short Overview. Then create a Markdown table with columns: "
        "Priority | Task | Owner | Deadline | Status | Dependency / Blocker. Group or order tasks by priority. "
        "After the table, add Follow-up Questions and Suggested Next Step bullets. Use 'Not mentioned' where owner, "
        "deadline, status, or dependency is missing."
    ),
    "report": (
        "Create a client-ready report with clean sections, neutral tone, concise bullet-backed observations, "
        "and clear recommendations. Use tables sparingly for metrics, status, or comparisons only."
    ),
    "ask": (
        "Answer the user's question using the supplied text. Be precise, structured, and cite the relevant context "
        "in plain language. Use bullets or a small table if that makes the answer clearer."
    ),
}


COMMON_FORMAT_REQUIREMENTS = """FORMAT REQUIREMENTS:
- Use Markdown.
- Use clear headings with meaningful names, not generic labels.
- Use short paragraphs only for context. Use bullets for takeaways.
- Use tables sparingly. Tables are for repeated structured data only: tasks, owner/deadline/status lists, metrics, comparisons, or trackers.
- Do not use tables for narrative context, key takeaways, discussion summaries, risks, concerns, or next steps unless columns are genuinely needed.
- A good default shape is: short paragraph for context, bullets for insights, one table for tasks if needed, bullets for follow-ups.
- Avoid long dense paragraphs and repeated sentences.
- If the source is unclear, say exactly what is unclear instead of guessing.
"""


def _trim_text(text: str) -> tuple[str, bool]:
    raw = str(text or "").strip()
    limit = max(config.TEXT_SUMMARIZER_MAX_INPUT_CHARS, 20000)
    if len(raw) <= limit:
        return raw, False
    return raw[:limit], True


def _build_user_prompt(payload: SummarizerRequest, trimmed: bool) -> str:
    mode = (payload.mode or "professional").strip().lower()
    mode_instruction = MODE_GUIDANCE.get(mode, MODE_GUIDANCE["professional"])
    user_instruction = (payload.instruction or "").strip()
    title = (payload.title or "Untitled text").strip()
    text, _ = _trim_text(payload.text)

    parts = [
        f"TITLE: {title}",
        f"MODE: {mode}",
        f"TASK: {mode_instruction}",
        COMMON_FORMAT_REQUIREMENTS,
    ]
    if user_instruction:
        parts.append(f"USER REQUEST: {user_instruction}")
    if trimmed:
        parts.append(
            "NOTE: The source text was trimmed to fit the configured input limit. "
            "Mention that the summary is based on the supplied portion."
        )
    parts.append(f"SOURCE TEXT:\n{text}")
    return "\n\n".join(parts)


def _build_messages(payload: SummarizerRequest, trimmed: bool) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in payload.history[-8:]:
        content = item.content.strip()
        if content:
            messages.append({"role": item.role, "content": content})
    messages.append({"role": "user", "content": _build_user_prompt(payload, trimmed)})
    return messages


@router.get("/status")
async def summarizer_status(request: Request):
    require_authenticated_request(request)
    ready = bool(config.OPENAI_API_KEY)
    provider = "OpenAI-compatible API"
    if "openrouter.ai" in config.OPENAI_BASE_URL:
        provider = "OpenRouter"
    return {
        "ready": ready,
        "provider": provider,
        "model": config.TEXT_SUMMARIZER_MODEL,
        "detail": (
            f"{provider} text summarizer ready: {config.TEXT_SUMMARIZER_MODEL}"
            if ready
            else "Text summarizer is disabled. Add OPENAI_API_KEY to enable it."
        ),
    }


@router.post("/chat")
async def summarize_text(payload: SummarizerRequest, request: Request):
    require_authenticated_request(request)

    source_text, trimmed = _trim_text(payload.text)
    if not source_text:
        raise HTTPException(status_code=400, detail="Add text or use the current transcript before summarizing.")
    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is missing. Configure it before using Text Summarizer.")

    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    if config.OPENAI_PROJECT:
        headers["OpenAI-Project"] = config.OPENAI_PROJECT

    body = {
        "model": config.TEXT_SUMMARIZER_MODEL,
        "messages": _build_messages(payload, trimmed),
        "temperature": 0.2,
    }

    try:
        response = httpx.post(
            f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
            timeout=config.OPENAI_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Text summarizer request timed out.") from exc
    except httpx.HTTPError as exc:
        logger.error("Text summarizer request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach the text summarizer provider.") from exc

    if response.status_code != 200:
        logger.error("Text summarizer provider returned %s: %s", response.status_code, response.text)
        raise HTTPException(
            status_code=502,
            detail=f"Text summarizer provider returned status {response.status_code}.",
        )

    data = response.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    content = str(content or "").strip()
    if not content:
        raise HTTPException(status_code=502, detail="Text summarizer returned an empty response.")

    return {
        "answer": content,
        "model": config.TEXT_SUMMARIZER_MODEL,
        "provider": "OpenRouter" if "openrouter.ai" in config.OPENAI_BASE_URL else "OpenAI-compatible API",
        "trimmed": trimmed,
    }
