import google.generativeai as genai

from core.config import gemini_key

_MODEL_NAME = "gemini-1.5-flash"


def _model():
    key = gemini_key()
    if not key:
        raise RuntimeError("Gemini key missing. Set llm.gemini_api_key in secrets.toml or override in Settings.")
    genai.configure(api_key=key)
    return genai.GenerativeModel(_MODEL_NAME)


def generate(prompt: str, temperature: float = 0.6, max_tokens: int = 800) -> str:
    resp = _model().generate_content(
        prompt,
        generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
    )
    return resp.text.strip()
