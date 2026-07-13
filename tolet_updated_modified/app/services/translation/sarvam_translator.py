import os
import requests
from dotenv import load_dotenv

load_dotenv()


class SarvamTranslator:

    def __init__(self):

        self.api_key = os.getenv("SARVAM_API_KEY")
        self.url = "https://api.sarvam.ai/translate"

    def translate(self, query: str, source_lang="ta-IN", target_lang="en-IN"):

        try:

            payload = {
                "input": query,
                "source_language_code": source_lang,
                "target_language_code": target_lang
            }

            headers = {
                "API-Subscription-Key": self.api_key,
                "Content-Type": "application/json"
            }

            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=10
            )

            data = response.json()

            # Bug fix: data.get("translated_text", query) returns None when the
            # key exists but its value is null in the JSON. Use `or query` instead.
            translated = data.get("translated_text") or query
            return translated

        except Exception as error:
            print("Sarvam Translation Error:", error)
            return query

    def translate_tamil_to_english(self, text: str):
        return self.translate(text, "ta-IN", "en-IN")

    def translate_tanglish_to_english(self, text: str):
        # Only hit the Sarvam API when text actually contains Tamil script
        # or known Tanglish words. Plain English queries (e.g. "list properties
        # from noida") must pass through unchanged — sending them to the
        # Tamil→English API risks a null/garbled response that crashes callers.
        is_tamil_script = any('\u0b80' <= ch <= '\u0bff' for ch in text)
        tanglish_markers = [
            "venum", "venam", "ennaku", "veedu", "iruka",
            "iruku", "theva", "thevai", "flatu", "pakathula"
        ]
        has_tanglish = any(marker in text.lower() for marker in tanglish_markers)

        if is_tamil_script or has_tanglish:
            return self.translate(text, "ta-IN", "en-IN")

        # Pure English — skip the API call entirely
        return text