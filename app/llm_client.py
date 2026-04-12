from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


def llm_is_configured() -> bool:
    return bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model)


async def summarize_with_llm_history(
    question: str,
    tool_payload: dict[str, Any] | None,
    history: list[dict[str, str]],
    analytics_mode: bool = True,
) -> str | None:
    if not llm_is_configured():
        return None

    system_content = (
        "You are ABS Insight Copilot for baseball analysts/coaches. "
        "Be concise, natural, and conversational."
    )
    if analytics_mode:
        system_content += (
            " For analytical prompts, respond in markdown with sections: "
            "### Answer, ### Supporting Stats, ### Recommended Actions."
        )

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": system_content,
        }
    ]
    for turn in history[-10:]:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    if tool_payload is not None:
        messages.append(
            {
                "role": "user",
                "content": f"Question: {question}\n\nTool output:\n{tool_payload}",
            }
        )
    else:
        messages.append({"role": "user", "content": question})

    payload = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    base = settings.llm_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{base}/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            return choices[0]["message"]["content"]
    except httpx.HTTPError:
        return None
