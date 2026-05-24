import os
import google.generativeai as genai
from core.config import config

# ── Provider detection ─────────────────────────────────────────────────────
# Routing logic (checked in order):
#
#   1. model starts with "claude-"  →  Anthropic SDK
#      (Anthropic's API is not OpenAI-compatible; needs its own SDK and headers)
#
#   2. base_url is set              →  OpenAI-compatible SDK
#      (Ollama, Azure OpenAI, vLLM, LM Studio, LocalAI, etc.)
#
#   3. neither                      →  native Gemini SDK  (default)
#
# Embeddings always use the native Gemini SDK regardless of text-gen provider,
# because the Rust engine was seeded with 1536-dim Gemini vectors.

_genai_model: genai.GenerativeModel | None = None
_openai_client   = None    # openai.OpenAI,    imported lazily
_anthropic_client = None   # anthropic.Anthropic, imported lazily


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_api_key() -> str:
    key = os.getenv("AI_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Add AI_API_KEY=<your-key> to your .env file "
            "or set it as an environment variable."
        )
    return key


def _is_claude() -> bool:
    return config.ai_integration.model_to_use.startswith("claude-")


# ── Lazy client initialisers ───────────────────────────────────────────────

def _get_genai_model() -> genai.GenerativeModel:
    """Native Gemini SDK — used when no base_url is set and model isn't Claude."""
    global _genai_model
    if _genai_model is None:
        genai.configure(api_key=_resolve_api_key())
        model_name = config.ai_integration.model_to_use
        _genai_model = genai.GenerativeModel(model_name)
        print(f"✅ LLM client initialised — Gemini SDK | model: {model_name}")
    return _genai_model


def _get_openai_client():
    """OpenAI-compatible SDK — used when base_url is set (Ollama, Azure, vLLM…)."""
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "The 'openai' package is required when base_url is set in connectors.yaml. "
                "Install it with: pip install openai"
            )
        base_url   = config.ai_integration.base_url
        model_name = config.ai_integration.model_to_use
        _openai_client = OpenAI(api_key=_resolve_api_key(), base_url=base_url)
        print(f"✅ LLM client initialised — OpenAI-compatible SDK | url: {base_url} | model: {model_name}")
    return _openai_client


def _get_anthropic_client():
    """Native Anthropic SDK — used when model_to_use starts with 'claude-'."""
    global _anthropic_client
    if _anthropic_client is None:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "The 'anthropic' package is required when using a Claude model. "
                "Install it with: pip install anthropic"
            )
        model_name = config.ai_integration.model_to_use
        _anthropic_client = anthropic.Anthropic(api_key=_resolve_api_key())
        print(f"✅ LLM client initialised — Anthropic SDK | model: {model_name}")
    return _anthropic_client


# ── Public API ─────────────────────────────────────────────────────────────

def get_vector_embedding(text: str) -> list[float]:
    """
    Generates a strict 1,536-dimension embedding array for the Rust engine.
    Always uses the native Gemini SDK regardless of the text-generation provider.
    """
    genai.configure(api_key=_resolve_api_key())
    try:
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=text,
            output_dimensionality=1536,
        )
        return result['embedding']
    except Exception as e:
        print(f"❌ Gemini Embedding Error for text '{text[:60]}...': {e}")
        return [0.0] * 1536


def generate_text(prompt: str) -> str:
    """
    Sends a prompt to the configured LLM and returns the text response.

    Provider is selected automatically:
      claude-*  →  Anthropic SDK
      base_url  →  OpenAI-compatible SDK
      default   →  Native Gemini SDK
    """
    if _is_claude():
        # ── Anthropic path ───────────────────────────────────────────────────
        client   = _get_anthropic_client()
        response = client.messages.create(
            model=config.ai_integration.model_to_use,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip().strip('"')

    elif config.ai_integration.base_url:
        # ── OpenAI-compatible path (Ollama, Azure OpenAI, vLLM, etc.) ────────
        client   = _get_openai_client()
        response = client.chat.completions.create(
            model=config.ai_integration.model_to_use,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip().strip('"')

    else:
        # ── Native Gemini path (default) ─────────────────────────────────────
        response = _get_genai_model().generate_content(prompt)
        return response.text.strip().strip('"')
