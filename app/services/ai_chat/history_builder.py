from services.llm.prompts import RESPONSE_SYSTEM_PROMPT




class HistoryBuilder:


    def build(
        self,
        session_messages: list,
        system_prompt: str = None
    ) -> list:

        messages = []


        messages.append({
            "role": "system",
            "content": system_prompt or RESPONSE_SYSTEM_PROMPT
        })


        for msg in session_messages:
            if msg.get("role") in ("user", "assistant"):
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        return messages

    # ===================================
    # Build Context Summary String
    # Used when you need a compact text
    # summary of recent turns (for prompts
    # that inject context as text, not
    # as a messages[] array)
    # ===================================
    def build_context_summary(
        self,
        session_messages: list,
        last_n: int = 6
    ) -> str:

        recent = [
            m for m in session_messages
            if m.get("role") in ("user", "assistant")
        ][-last_n:]

        if not recent:
            return "No prior conversation."

        lines = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role}: {msg['content']}")

        return "\n".join(lines)

    # ===================================
    # Build Property Context String
    # Injects property details into the
    # current user message so the LLM
    # knows what was shown
    # ===================================
    def build_user_message_with_context(
        self,
        query: str,
        filters: dict,
        properties: list,
        intent: str
    ) -> str:

        prop_text = ""

        if properties:
            # For property_discussion intent, inject full property details
            # so the AI can answer questions about bathrooms, pets, deposit etc.
            is_detail_intent  = intent in ("property_discussion", "recommendation")
            is_contact_intent = intent == "contact_request"
            prop_text = "\n\nProperties shown to user this turn:\n"
            for p in properties:
                if is_contact_intent:
                    # Contact block — only owner info needed
                    preferred_str = ", ".join(p.get("preferred_time") or []) or "anytime"
                    prop_text += (
                        f"- Title: {p.get('title')}\n"
                        f"  Location: {p.get('locality') or p.get('location')}, {p.get('city')}\n"
                        f"  Owner name: {p.get('owner_name') or 'Not listed'}\n"
                        f"  Owner phone: {p.get('owner_phone') or 'Not listed'}\n"
                        f"  Owner whatsapp: {p.get('owner_whatsapp') or 'Not listed'}\n"
                        f"  Preferred contact time: {preferred_str}\n\n"
                    )
                elif is_detail_intent:
                    # Full detail block — used when user asks "tell me more"
                    amenities_str = ", ".join(p.get("amenities") or []) or "None listed"
                    prop_text += (
                        f"- Title: {p.get('title')}\n"
                        f"  Location: {p.get('locality') or p.get('location')}, {p.get('city')}\n"
                        f"  Price: ₹{p.get('price')}/month\n"
                        f"  BHK: {p.get('bhk')}\n"
                        f"  Sq.ft: {p.get('sq_ft') or 'N/A'}\n"
                        f"  Furnished: {p.get('furnished')}\n"
                        f"  Property type: {p.get('property_type')}\n"
                        f"  Floor: {p.get('floor')}/{p.get('total_floors')}\n"
                        f"  Bathrooms: {p.get('bathroom_count')}\n"
                        f"  Balconies: {p.get('balcony_count')}\n"
                        f"  Near metro: {p.get('near_metro')}\n"
                        f"  Bachelor friendly: {p.get('bachelor_friendly')}\n"
                        f"  Family friendly: {p.get('family_friendly')}\n"
                        f"  Pets allowed: {p.get('pets_allowed') or 'No'}\n"
                        f"  Security deposit: {p.get('security_deposit') or 'N/A'}\n"
                        f"  Maintenance: ₹{p.get('maintenance') or 0}/month\n"
                        f"  Notice period: {p.get('notice_period') or 'N/A'}\n"
                        f"  Available from: {p.get('available_from') or 'N/A'}\n"
                        f"  No broker: {p.get('no_broker')}\n"
                        f"  Amenities: {amenities_str}\n"
                        f"  Additional details: {p.get('additional_details') or 'None'}\n\n"
                    )
                else:
                    # Compact summary — used for initial search results
                    prop_text += (
                        f"- {p.get('title')} | {p.get('location')} | "
                        f"₹{p.get('price')} | {p.get('bhk')}BHK | "
                        f"{p.get('furnished')} | "
                        f"Metro: {p.get('near_metro')} | "
                        f"Bachelor: {p.get('bachelor_friendly')} | "
                        f"Family: {p.get('family_friendly')}\n"
                    )
        else:
            prop_text = "\n\nNo properties found for this query."

        filter_text = ""
        if any(filters.values()):
            parts = []
            if filters.get("location"):
                parts.append(f"Location: {filters['location']}")
            if filters.get("bhk"):
                parts.append(f"BHK: {filters['bhk']}")
            if filters.get("max_price"):
                parts.append(f"Budget: ₹{filters['max_price']}")
            if filters.get("furnished"):
                parts.append(f"Furnished: {filters['furnished']}")
            if filters.get("near_metro"):
                parts.append("Near metro: yes")
            if filters.get("tenant_type"):
                parts.append(f"Tenant: {filters['tenant_type']}")
            filter_text = "\nFilters applied: " + ", ".join(parts)

        return (
            f"User message: {query}\n"
            f"Detected intent: {intent}"
            f"{filter_text}"
            f"{prop_text}\n\n"
            f"Respond naturally as Tolet AI."
        )

    # ===================================
    # Trim messages to stay within
    # token budget (approx 3000 tokens)
    # Always keeps system prompt + last N
    # ===================================
    def trim_to_budget(
        self,
        messages: list,
        max_messages: int = 20
    ) -> list:

        if len(messages) <= max_messages:
            return messages

        # Keep system prompt + last (max_messages-1) turns
        system = messages[0]
        rest   = messages[1:]
        trimmed = rest[-(max_messages - 1):]

        return [system] + trimmed