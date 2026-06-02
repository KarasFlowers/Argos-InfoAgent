"""
LLM tier-spec parsing utilities.

Extracted from ``app.services.llm.client`` so that both the LLM client
and the database seed logic (``app.core.db``) can import the parser
without cross-layer coupling.
"""

from __future__ import annotations


# Well-known provider base URLs
PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "silicon": "https://api.siliconflow.cn/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}


def parse_tier_spec(
    spec: str,
    fallback_base_url: str,
    fallback_api_key: str | None,
) -> tuple[str, str | None, str] | None:
    """Parse a tier spec like ``'openai:gpt-4o-mini'`` into *(base_url, api_key, model)*.

    Supported formats:
      - ``""``                       → ``None`` (use default)
      - ``"model-name"``             → same base_url/api_key, different model
      - ``"provider:model-name"``    → well-known provider base_url, same api_key
      - ``"base_url|api_key|model"`` → fully custom endpoint (pipe-separated)
    """
    spec = spec.strip()
    if not spec:
        return None

    # Fully custom: "https://api.example.com/v1|sk-xxx|model-name"
    if "|" in spec:
        parts = spec.split("|", 2)
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        return None

    # Well-known providers
    if ":" in spec:
        provider, model = spec.split(":", 1)
        provider_lower = provider.lower()
        base_url = PROVIDER_URLS.get(provider_lower, fallback_base_url)
        return base_url, fallback_api_key, model

    # Plain model name — same endpoint, different model
    return fallback_base_url, fallback_api_key, spec


# ---------------------------------------------------------------------------
# Output language control
# ---------------------------------------------------------------------------

def language_directive(code: str | None) -> str:
    """Return a system-prompt directive that forces the LLM output language.

    Args:
        code: Board output_language — ``"zh"``, ``"en"``, or ``"auto"``/None.

    Returns:
        A directive string to append to the system prompt, or ``""`` when
        ``auto`` (let the model follow the source language).
    """
    normalized = (code or "auto").strip().lower()
    if normalized == "zh":
        return (
            "\n\nLANGUAGE REQUIREMENT: You MUST write ALL output "
            "(overview, headlines, key_points, tags, and any narrative text) "
            "in Simplified Chinese, regardless of the source article language."
        )
    if normalized == "en":
        return (
            "\n\nLANGUAGE REQUIREMENT: You MUST write ALL output "
            "(overview, headlines, key_points, tags, and any narrative text) "
            "in English, regardless of the source article language."
        )
    return ""
