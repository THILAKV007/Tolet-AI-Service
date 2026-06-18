from services.llm.llm_client import LLMClient
from services.llm.prompts import RESPONSE_SYSTEM_PROMPT
from services.ai_chat.history_builder import HistoryBuilder


DETAIL_REQUEST_SIGNALS = [
    "yeah", "yes", "sure", "of course",
    "ofcourse", "okay", "ok", "go ahead",
    "tell me more", "more details", "details",
    "explain", "describe", "what else",
    "sounds good", "interesting", "nice",
    "cool", "great", "please", "yep", "yup"
]


class ResponseAI:

    def __init__(self):
        self.llm     = LLMClient()
        self.builder = HistoryBuilder()


    def generate(
        self,
        query: str,
        filters: dict,
        properties: list,
        intent: str,
        session_messages: list = None,
        geo_original_location: str = None,
        geo_expanded_areas: list = None
    ) -> str:

        try:

            query_lower   = query.strip().lower()
            is_detail_ask = (
                intent == "property_discussion" and
                any(signal in query_lower for signal in DETAIL_REQUEST_SIGNALS)
            )
            max_tokens = 800 if is_detail_ask else 600

            current_user_message = self.builder.build_user_message_with_context(
                query=query,
                filters=filters,
                properties=properties,
                intent=intent,
                geo_original_location=geo_original_location,
                geo_expanded_areas=geo_expanded_areas
            )

            messages = self.builder.build(
                session_messages=session_messages or [],
                system_prompt=RESPONSE_SYSTEM_PROMPT
            )

            messages.append({
                "role": "user",
                "content": current_user_message
            })


            messages = self.builder.trim_to_budget(messages, max_messages=22)


            return self.llm.chat_with_history(
                messages=messages,
                temperature=0.9,
                max_tokens=max_tokens
            )

        except Exception as e:
            print(f"[ResponseAI] generate error: {e}")
            return (
                "Something tripped up on my end — "
                "mind rephrasing that?"
            )


    def generate_knowledge_response(
        self,
        query: str,
        knowledge: str,
        session_messages: list = None
    ) -> str:

        try:
            system_prompt = """
You are Tolet AI — a conversational rental property assistant for India.
Answer ONLY using the provided Tolet AI knowledge context.
Be warm, natural, and vary your phrasing every time.
Minimum 3 lines. Never robotic or repetitive.
"""
            messages = [{"role": "system", "content": system_prompt}]

            if session_messages:
                for msg in session_messages[-6:]:
                    if msg.get("role") in ("user", "assistant"):
                        messages.append(msg)

            messages.append({
                "role": "user",
                "content": (
                    f"User Question: {query}\n"
                    f"Tolet AI Knowledge Context: {knowledge}\n\n"
                    f"Answer conversationally using only the knowledge above."
                )
            })

            return self.llm.chat_with_history(
                messages=messages,
                temperature=0.9,
                max_tokens=500
            )

        except Exception:
            return (
                "Tolet AI helps you find rental homes across India — "
                "just tell me what you're looking for!"
            )