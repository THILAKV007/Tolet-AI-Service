import json

from services.llm.llm_client import (
    LLMClient
)


class LLMExtractor:

    def __init__(self):

        self.llm = LLMClient()

    def extract(

        self,

        query: str
    ):

        try:

            system_prompt = """

You are an AI extraction engine.

Extract rental property filters
from user query.

Return ONLY valid JSON.

Do not explain anything.

JSON format:

{
    "bhk": int or null,
    "max_price": int or null,
    "location": string or null,
    "property_type": "residential" or "commercial" or "paid_guest" or null,
    "furnished": string or null,
    "near_metro": true or false,
    "tenant_type": string or null,
    "budget_preference": string or null
}

Rules:

- Output ONLY JSON
- No markdown
- No explanation
- No extra text
- If value missing return null
- near_metro must be boolean
- property_type MUST be exactly one of "residential", "commercial",
  "paid_guest", or null — this must match the database's stored values
  exactly. Map "pg" / "hostel" / "paying guest" → "paid_guest",
  "flat" / "apartment" / "house" / "villa" → "residential",
  "shop" / "office" / "godown" → "commercial".

"""


            user_prompt = f"""

Query:
{query}

Extract filters.
"""


            response = self.llm.chat(

                system_prompt=system_prompt,

                user_prompt=user_prompt,

                temperature=0.1,

                max_tokens=200
            )

            response = response.strip()

            response = response.replace(
                "```json",
                ""
            )

            response = response.replace(
                "```",
                ""
            )

            extracted_filters = json.loads(
                response
            )


            if not isinstance(

                extracted_filters,

                dict
            ):

                return {}

            return extracted_filters

        except Exception as error:

            print(
                "LLM Extraction Error:",
                error
            )

            return {}