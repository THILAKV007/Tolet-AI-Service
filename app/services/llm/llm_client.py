import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


# ── Model Configuration ────────────────────────────────────────────────────────
# Set LLM_PROVIDER in .env to switch between providers:
#   "openrouter"  → uses OPENROUTER_API_KEY  (default, cloud models)
#   "ollama"      → uses local Ollama server  (no API key needed)
#   "openai"      → uses OPENAI_API_KEY       (direct OpenAI)
#
# Set DEFAULT_MODEL in .env to pick the exact model, e.g.:
#   DEFAULT_MODEL=deepseek/deepseek-chat-v3-0324   (DeepSeek Chat V3 — RECOMMENDED)
#   DEFAULT_MODEL=meta-llama/llama-3.1-8b-instruct  (OpenRouter Llama3)
#   DEFAULT_MODEL=openai/gpt-4.1                    (OpenRouter GPT-4.1)
#   DEFAULT_MODEL=llama3                            (local Ollama)
#   DEFAULT_MODEL=gpt-4o-mini                       (direct OpenAI)
# ──────────────────────────────────────────────────────────────────────────────

_PROVIDER      = os.getenv("LLM_PROVIDER", "openrouter").lower()
_DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "")

# Provider-specific defaults when DEFAULT_MODEL is not set
_PROVIDER_DEFAULTS = {
    "openrouter": "deepseek/deepseek-chat-v3-0324",   # Fast, smart, cost-effective
    "ollama":     "llama3",
    "openai":     "gpt-4o-mini",
}

_PROVIDER_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama":     os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    "openai":     "https://api.openai.com/v1",
}

_PROVIDER_API_KEYS = {
    "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
    "ollama":     "ollama",   # Ollama doesn't need a real key
    "openai":     os.getenv("OPENAI_API_KEY", ""),
}


def _resolve_default_model() -> str:
    """Return the model string to use, from env or provider default."""
    if _DEFAULT_MODEL:
        return _DEFAULT_MODEL
    return _PROVIDER_DEFAULTS.get(_PROVIDER, "deepseek/deepseek-chat-v3-0324")


def _build_client() -> OpenAI:
    base_url = _PROVIDER_BASE_URLS.get(_PROVIDER)
    api_key  = _PROVIDER_API_KEYS.get(_PROVIDER, "")
    if not base_url:
        raise ValueError(f"[LLMClient] Unknown LLM_PROVIDER: '{_PROVIDER}'")
    return OpenAI(api_key=api_key or "no-key", base_url=base_url)


class LLMClient:

    def __init__(self):
        self.client        = _build_client()
        self.default_model = _resolve_default_model()
        print(
            f"[LLMClient] Provider: {_PROVIDER.upper()} | "
            f"Model: {self.default_model}"
        )

    # ── JSON mode support check ────────────────────────────────────────────────
    # DeepSeek and OpenAI models support response_format=json_object natively.
    # Ollama and Llama-based models don't — we fall back to prompt-based extraction.
    # ──────────────────────────────────────────────────────────────────────────
    @property
    def _supports_json_mode(self) -> bool:
        """True for providers/models known to support response_format=json_object."""
        if _PROVIDER == "ollama":
            return False
        m = self.default_model.lower()
        # Llama models on OpenRouter don't reliably support JSON mode
        if "llama" in m:
            return False
        # DeepSeek, GPT, Gemini — all support JSON mode
        return True

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> str:

        try:
            response = self.client.chat.completions.create(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            content = response.choices[0].message.content
            return content if content is not None else "I'm having trouble processing your request right now."

        except Exception as e:
            print(f"[LLMClient] chat error: {e}")
            return "I'm having trouble processing your request right now."


    def chat_with_history(
        self,
        messages: list,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 600
    ) -> str:
        """
        Main conversational call. Uses full message history.
        temperature=0.7 gives DeepSeek a natural, warm tone without being random.
        """
        try:
            response = self.client.chat.completions.create(
                model=model or self.default_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            content = response.choices[0].message.content
            return content if content is not None else "I'm having trouble processing your request right now."

        except Exception as e:
            print(f"[LLMClient] chat_with_history error: {e}")
            return "I'm having trouble processing your request right now."


    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        temperature: float = 0.1,
        max_tokens: int = 1200
    ) -> dict:

        try:
            kwargs = dict(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            # DeepSeek, GPT, Gemini support json_object mode — use it for clean output
            if self._supports_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            else:
                # Inject JSON instruction for models that don't support it natively
                kwargs["messages"][0]["content"] = (
                    system_prompt.rstrip() +
                    "\n\nIMPORTANT: Respond ONLY with valid JSON. No explanation, no markdown, no backticks."
                )

            response = self.client.chat.completions.create(**kwargs)

            raw = response.choices[0].message.content

            if not raw:
                print("[LLMClient] chat_json received empty/None content")
                return {}

            raw = raw.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            return json.loads(raw)

        except json.JSONDecodeError as e:
            print(f"[LLMClient] JSON parse error: {e}")
            return {}

        except Exception as e:
            print(f"[LLMClient] chat_json error: {e}")
            return {}


    def classify(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None
    ) -> str:

        try:
            response = self.client.chat.completions.create(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt}
                ],
                temperature=0.0,
                max_tokens=20
            )
            content = response.choices[0].message.content

            if not content:
                print("[LLMClient] classify received None content, defaulting")
                return "property_search"
            return content.strip().lower()

        except Exception as e:
            print(f"[LLMClient] classify error: {e}")
            return "property_search"
