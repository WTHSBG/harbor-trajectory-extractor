from __future__ import annotations


def get_api_key_var_names_from_model_name(model_name: str | None) -> list[str]:
    if not model_name:
        return []
    provider = model_name.split("/", 1)[0].lower() if "/" in model_name else ""
    mapping = {
        "anthropic": ["ANTHROPIC_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "xai": ["XAI_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "mistral": ["MISTRAL_API_KEY"],
    }
    return mapping.get(provider, [])

