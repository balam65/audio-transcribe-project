"""
Summary Generation Service.
Generates meeting summaries using a configured provider.

Supported summary providers:
- `openai`: OpenAI or any OpenAI-compatible API router/base URL
- `ollama`: Local Ollama

If the configured provider is unavailable, the app falls back to a
deterministic local summary so the transcript is still saved with notes.

CRITICAL ACCURACY RULES:
- Only extract information explicitly stated in the transcript
- Never fabricate names, numbers, dates, deadlines, or commitments
- If not clearly mentioned, write "Not mentioned"
- Action items must only be created if explicitly mentioned or assigned
"""

import json
import logging
import re
from collections import Counter
from typing import Optional

import httpx

from config import config

logger = logging.getLogger(__name__)

# System prompt enforcing strict accuracy rules
SUMMARY_SYSTEM_PROMPT = """You are a meeting transcript analyzer. Your job is to extract information ONLY from the provided transcript.

CRITICAL RULES:
1. NEVER fabricate, assume, or infer information not explicitly stated in the transcript.
2. NEVER guess names, numbers, dates, deadlines, or commitments.
3. If something is marked as [unclear] or [inaudible], acknowledge it as unclear.
4. Action items must ONLY be created if explicitly mentioned or assigned in the transcript.
5. Do not add context or background knowledge — only use what's in the transcript.
6. If the transcript is too short or unclear to generate a meaningful summary, say so.
7. Preserve technical terms, product names, and acronyms exactly as spoken.
8. If a speaker is labeled "Speaker 1" etc., use those labels — do not assign names.
9. If a field has no content from the transcript, write "Not mentioned" instead of guessing.

You must respond ONLY with valid JSON in this exact format:
{
  "summary": "A concise 2-4 paragraph summary of the meeting",
  "key_points": ["Point 1", "Point 2"],
  "decisions": ["Decision 1", "Decision 2"],
  "action_items": [
    {"task": "Description", "owner": "Speaker X or Unassigned", "deadline": "If mentioned or Not specified"}
  ],
  "open_questions": ["Question 1", "Question 2"]
}

If any section has no content, return an empty array for that field.
Only include items that were EXPLICITLY discussed. Do not invent anything."""


def generate_summary(transcript: str, meeting_title: str = "") -> dict:
    """
    Generate a structured meeting summary using the configured provider.

    Falls back gracefully if the provider is not available — transcript is still saved.
    Returns dict with: summary, key_points, decisions, action_items, open_questions
    """
    if not transcript or len(transcript.strip()) < 50:
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Transcript too short to generate a richer summary.",
        )

    engine = config.SUMMARY_ENGINE.lower()

    if engine == "openai":
        return _generate_openai_summary(transcript, meeting_title)
    if engine == "ollama":
        return _generate_ollama_summary(transcript, meeting_title)

    logger.warning("Unsupported summary engine %s — using local fallback", config.SUMMARY_ENGINE)
    return _local_fallback_summary(
        transcript,
        meeting_title,
        f"Generated from the transcript because SUMMARY_ENGINE `{config.SUMMARY_ENGINE}` is not supported.",
    )


def get_summary_provider_status() -> dict:
    """Return health information for the configured summary provider."""
    engine = config.SUMMARY_ENGINE.lower()

    if engine == "openai":
        key_present = bool(config.OPENAI_API_KEY)
        provider_name = "OpenAI-compatible API"
        if "openrouter.ai" in config.OPENAI_BASE_URL:
            provider_name = "OpenRouter"

        return {
            "engine": "openai",
            "provider": provider_name,
            "reachable": key_present,
            "model_available": key_present,
            "ready": key_present,
            "detail": (
                f"{provider_name} ready: {config.SUMMARY_MODEL}"
                if key_present
                else "Fallback summary mode active. Add OPENAI_API_KEY to enable cloud summaries."
            ),
        }

    if engine == "ollama":
        ollama_status = get_ollama_status()
        detail = "Fallback summary mode active. Start Ollama to enable local AI summaries."
        if ollama_status["reachable"] and ollama_status["model_available"]:
            detail = f"Summary engine ready: Ollama {config.SUMMARY_MODEL}".strip()
        elif ollama_status["reachable"]:
            detail = f"Fallback summary mode active. Install model: ollama pull {config.SUMMARY_MODEL or 'llama3.1'}"

        return {
            "engine": "ollama",
            "provider": "Ollama",
            "reachable": ollama_status["reachable"],
            "model_available": ollama_status["model_available"],
            "ready": ollama_status["reachable"] and ollama_status["model_available"],
            "detail": detail,
        }

    return {
        "engine": engine,
        "provider": engine or "unknown",
        "reachable": False,
        "model_available": False,
        "ready": False,
        "detail": f"Fallback summary mode active. Unsupported SUMMARY_ENGINE `{config.SUMMARY_ENGINE}`.",
    }


def get_ollama_status() -> dict:
    """Check whether Ollama is reachable and the configured model is installed."""
    try:
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return {
                "reachable": False,
                "model_available": False,
            }

        data = resp.json()
        models = data.get("models", [])
        model_names = {
            (model.get("name") or model.get("model") or "").split(":")[0]
            for model in models
        }
        requested_name = config.SUMMARY_MODEL.split(":")[0]
        return {
            "reachable": True,
            "model_available": requested_name in model_names,
        }
    except Exception:
        return {
            "reachable": False,
            "model_available": False,
        }


def _build_user_prompt(transcript: str, meeting_title: str) -> str:
    """Build a consistent user prompt for supported providers."""
    return f"""Meeting Title: {meeting_title or 'Untitled Meeting'}

TRANSCRIPT:
{transcript}

Analyze this transcript and extract the summary, key discussion points, decisions made, action items with owners (if mentioned), and open questions.
Follow the rules strictly. Respond ONLY with valid JSON."""


def _normalize_summary_payload(result: dict, engine: str, note: str = "") -> dict:
    """Normalize provider JSON into the app's expected summary shape."""
    return {
        "summary": result.get("summary", ""),
        "key_points": result.get("key_points", []),
        "decisions": result.get("decisions", []),
        "action_items": result.get("action_items", []),
        "open_questions": result.get("open_questions", []),
        "note": note,
        "engine": engine,
    }


def _generate_openai_summary(transcript: str, meeting_title: str) -> dict:
    """Generate a structured meeting summary via OpenAI-compatible chat completions."""
    status = get_summary_provider_status()
    if not status["ready"]:
        logger.warning("OpenAI-compatible summary provider is not configured — using fallback summary")
        return _local_fallback_summary(transcript, meeting_title, status["detail"])

    try:
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        if config.OPENAI_PROJECT:
            headers["OpenAI-Project"] = config.OPENAI_PROJECT

        payload = {
            "model": config.SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(transcript, meeting_title)},
            ],
            "response_format": {"type": "json_object"},
        }

        response = httpx.post(
            f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=config.OPENAI_TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            logger.error("OpenAI-compatible provider returned status %s: %s", response.status_code, response.text)
            return _local_fallback_summary(
                transcript,
                meeting_title,
                f"Generated from the transcript because the cloud summary provider returned status {response.status_code}.",
            )

        data = response.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))

        if not content:
            return _local_fallback_summary(
                transcript,
                meeting_title,
                "Generated from the transcript because the cloud summary provider returned an empty response.",
            )

        result = json.loads(content)
        return _normalize_summary_payload(result, engine="openai")

    except json.JSONDecodeError as e:
        logger.error("Failed to parse OpenAI-compatible JSON response: %s", e)
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Generated from the transcript because the cloud summary response could not be parsed.",
        )
    except httpx.TimeoutException:
        logger.warning("OpenAI-compatible summary request timed out")
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Generated from the transcript because the cloud summary provider timed out.",
        )
    except Exception as e:
        logger.error("OpenAI-compatible summary generation error: %s", e)
        return _local_fallback_summary(
            transcript,
            meeting_title,
            f"Generated from the transcript because summary generation hit an error: {str(e)}",
        )


def _generate_ollama_summary(transcript: str, meeting_title: str) -> dict:
    """Generate a structured meeting summary using local Ollama."""
    ollama_status = get_ollama_status()
    if not ollama_status["reachable"]:
        logger.warning("Ollama not available — using local fallback summary")
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Generated from the transcript because Ollama is not running.",
        )
    if not ollama_status["model_available"]:
        logger.warning("Ollama model %s not installed — using fallback summary", config.SUMMARY_MODEL)
        return _local_fallback_summary(
            transcript,
            meeting_title,
            f"Generated from the transcript because the Ollama model `{config.SUMMARY_MODEL}` is not installed.",
        )

    try:
        response = httpx.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(transcript, meeting_title)},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 2000,
                },
                "format": "json",
            },
            timeout=120.0,
        )

        if response.status_code != 200:
            logger.error("Ollama returned status %s: %s", response.status_code, response.text)
            return _local_fallback_summary(
                transcript,
                meeting_title,
                f"Generated from the transcript because Ollama returned status {response.status_code}.",
            )

        data = response.json()
        content = data.get("message", {}).get("content", "")

        if not content:
            return _local_fallback_summary(
                transcript,
                meeting_title,
                "Generated from the transcript because Ollama returned an empty response.",
            )

        result = json.loads(content)
        return _normalize_summary_payload(result, engine="ollama")

    except json.JSONDecodeError as e:
        logger.error("Failed to parse Ollama JSON response: %s", e)
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Generated from the transcript because the Ollama response could not be parsed.",
        )
    except httpx.ConnectError:
        logger.warning("Cannot connect to Ollama — is it running?")
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Generated from the transcript because Ollama is not running.",
        )
    except httpx.TimeoutException:
        logger.warning("Ollama request timed out")
        return _local_fallback_summary(
            transcript,
            meeting_title,
            "Generated from the transcript because Ollama timed out.",
        )
    except Exception as e:
        logger.error("Summary generation error: %s", e)
        return _local_fallback_summary(
            transcript,
            meeting_title,
            f"Generated from the transcript because summary generation hit an error: {str(e)}",
        )


def _empty_summary(reason: str = "") -> dict:
    """Return an empty summary structure with an explanation."""
    return {
        "summary": reason,
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "note": "",
        "engine": "empty",
    }


def _local_fallback_summary(transcript: str, meeting_title: str, reason: str) -> dict:
    """Generate a deterministic extractive summary with no external model dependency."""
    utterances = _extract_utterances(transcript)
    if not utterances:
        return {
            **_empty_summary("No clear transcript content was available to summarize."),
            "note": reason,
            "engine": "local_fallback",
        }

    sentences = []
    for utterance in utterances:
        for sentence in _split_sentences(utterance["text"]):
            cleaned = sentence.strip()
            if cleaned:
                sentences.append(
                    {
                        "speaker": utterance["speaker"],
                        "text": cleaned,
                    }
                )

    if not sentences:
        return {
            **_empty_summary("No clear transcript content was available to summarize."),
            "note": reason,
            "engine": "local_fallback",
        }

    ranked = _rank_sentences([item["text"] for item in sentences])
    top_sentences = _ordered_unique(ranked[:4])

    summary_sentences = top_sentences[:3] or [sentences[0]["text"]]
    summary_text = " ".join(summary_sentences)

    decisions = _find_sentences(
        sentences,
        ("decide", "decided", "decision", "agreed", "approved", "resolved", "plan is"),
        limit=3,
    )
    open_questions = _ordered_unique(
        [item["text"] for item in sentences if "?" in item["text"]]
        + _find_sentences(
            sentences,
            ("question", "unclear", "need to know", "need to find out", "not sure"),
            limit=3,
        )
    )[:4]
    action_items = _build_action_items(sentences)

    return {
        "summary": summary_text,
        "key_points": top_sentences,
        "decisions": decisions,
        "action_items": action_items,
        "open_questions": open_questions,
        "note": reason,
        "engine": "local_fallback",
    }


def _extract_utterances(transcript: str) -> list[dict]:
    """Parse the formatted transcript into speaker-labelled utterances."""
    utterances = []
    current_speaker = "Speaker 1"

    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        speaker_match = re.match(r"^\[(?:\d{2}:){1,2}\d{2}\]\s+(.+?):$", line)
        if speaker_match:
            current_speaker = speaker_match.group(1).strip()
            continue

        text_match = re.match(r"^\[(?:\d{2}:){1,2}\d{2}\]\s+(.+)$", line)
        if text_match:
            text = text_match.group(1).strip()
        else:
            text = line

        if text:
            utterances.append({"speaker": current_speaker, "text": text})

    return utterances


def _split_sentences(text: str) -> list[str]:
    """Split transcript text into simple sentence-like units."""
    return [
        part.strip(" -")
        for part in re.split(r"(?<=[.!?])\s+|\s*[;•]\s*", text)
        if part.strip(" -")
    ]


def _rank_sentences(sentences: list[str]) -> list[str]:
    """Rank sentences with a simple word-frequency heuristic."""
    if not sentences:
        return []

    tokens = []
    for sentence in sentences:
        tokens.extend(
            token.lower()
            for token in re.findall(r"[a-zA-Z0-9']+", sentence)
            if len(token) > 2 and token.lower() not in _STOP_WORDS
        )

    frequencies = Counter(tokens)
    scored = []
    for sentence in sentences:
        score = sum(
            frequencies[token.lower()]
            for token in re.findall(r"[a-zA-Z0-9']+", sentence)
            if token.lower() in frequencies
        )
        scored.append((score, sentence))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [sentence for _, sentence in scored]


def _find_sentences(sentences: list[dict], keywords: tuple[str, ...], limit: int) -> list[str]:
    """Return transcript sentences containing any keyword."""
    matches = []
    for item in sentences:
        lowered = item["text"].lower()
        if any(keyword in lowered for keyword in keywords):
            matches.append(item["text"])
    return _ordered_unique(matches)[:limit]


def _build_action_items(sentences: list[dict]) -> list[dict]:
    """Extract likely action items from explicit task-oriented language."""
    action_patterns = (
        r"\bwill\b",
        r"\bneeds? to\b",
        r"\bfollow up\b",
        r"\bsend\b",
        r"\bshare\b",
        r"\bprepare\b",
        r"\breview\b",
        r"\bcheck\b",
        r"\bcreate\b",
        r"\bupdate\b",
    )
    actions = []

    for item in sentences:
        lowered = item["text"].lower()
        if any(re.search(pattern, lowered) for pattern in action_patterns):
            owner = item["speaker"] or "Unassigned"
            speaker_match = re.search(r"\b(Speaker\s+\d+)\b", item["text"])
            if speaker_match:
                owner = speaker_match.group(1)
            actions.append(
                {
                    "task": item["text"],
                    "owner": owner,
                    "deadline": "Not specified",
                }
            )

    unique = []
    seen = set()
    for action in actions:
        key = action["task"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(action)
        if len(unique) == 4:
            break

    return unique


def _ordered_unique(items: list[str]) -> list[str]:
    """Keep order while dropping duplicates and overly short fragments."""
    unique = []
    seen = set()
    for item in items:
        normalized = item.strip()
        if len(normalized) < 8:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


_STOP_WORDS = {
    "the", "and", "that", "this", "with", "from", "they", "have", "were", "their",
    "about", "there", "would", "could", "should", "into", "because", "which", "while",
    "when", "what", "where", "your", "just", "then", "them", "said", "also", "been",
    "into", "over", "than", "will", "only", "some", "more", "very", "here", "after",
}
