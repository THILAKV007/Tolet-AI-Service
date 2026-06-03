import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class LLMClient:

    def __init__(self):

        self.client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1"
        )

        self.default_model = "openai/gpt-4.1-mini"

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
        temperature: float = 0.9,
        max_tokens: int = 500
    ) -> str:

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
            response = self.client.chat.completions.create(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )

            raw = response.choices[0].message.content

            if not raw:
                print("[LLMClient] chat_json received empty/None content")
                return {}


            raw = raw.strip()
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