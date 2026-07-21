from services.llm.prompts import RESPONSE_SYSTEM_PROMPT
from services.ai_chat.price_formatter import format_price


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
    # ===================================
    def build_user_message_with_context(
        self,
        query: str,
        filters: dict,
        properties: list,
        intent: str,
        geo_original_location: str = None,
        geo_expanded_areas: list = None,
        owner_type_counts: dict = None,
        owner_type_area: str = None
    ) -> str:

        prop_text = ""

        if properties:
            is_detail_intent  = intent in ("property_discussion", "recommendation")
            is_contact_intent = intent == "contact_request"
            prop_text = "\n\nProperties shown to user this turn:\n"
            for p in properties:
                if is_contact_intent:
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
                    amenities_str = ", ".join(p.get("amenities") or []) or "None listed"

                    # ── posted_by: "direct owner" or "broker" ─────────────────
                    # Normalise the raw value from MongoDB so the AI always
                    # receives a clean, unambiguous label it can act on.
                    raw_posted_by = (p.get("posted_by") or "").strip().lower()
                    if "direct" in raw_posted_by or raw_posted_by in ("owner", "direct_owner"):
                        posted_by_label = "direct owner"
                    elif "broker" in raw_posted_by:
                        # handles: 'broker', 'broker_property', 'broker_propert' (truncated)
                        posted_by_label = "broker"
                    else:
                        posted_by_label = raw_posted_by.replace("_", " ") or "N/A"
                    # ─────────────────────────────────────────────────────────

                    is_pg = (p.get("propertyType") or "").lower() == "paid_guest"

                    # Build core block; for PG, swap BHK/sqft for PG-specific fields
                    pg_fields = (
                        f"  AC/Non-AC: {p.get('unit_config') or 'N/A'}\n"
                        f"  Occupancy: {p.get('occupancy') or 'N/A'}\n"
                        f"  Gender: {p.get('gender') or 'any'}\n"
                    ) if is_pg else (
                        f"  BHK: {p.get('bhk')}\n"
                        f"  Sq.ft: {p.get('sq_ft') or 'N/A'}\n"
                    )

                    prop_text += (
                        f"- Title: {p.get('title')}\n"
                        f"  Location: {p.get('locality') or p.get('location')}, {p.get('city')}\n"
                        f"  Price: {format_price(p)}\n"
                        f"  Property type: {p.get('propertyType')}\n"
                        + pg_fields
                        + f"  Furnished: {p.get('furnished')}\n"
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
                        f"  Property age: {p.get('property_age') or 'N/A'}\n"
                        f"  Payment via: {p.get('payment_via') or 'N/A'}\n"
                        f"  Posted by: {posted_by_label}\n"
                        f"  No broker: {p.get('no_broker')}\n"
                        f"  Amenities: {amenities_str}\n"
                        f"  Additional details: {p.get('additional_details') or 'None'}\n\n"
                    )
                else:
                    # ── Compact card — include property type so AI never
                    # sees "None BHK" or hallucinates PG/commercial details ──
                    raw_posted_by = (p.get("posted_by") or "").strip().lower()
                    if "direct" in raw_posted_by or raw_posted_by in ("owner", "direct_owner"):
                        posted_by_label = "direct owner"
                    elif "broker" in raw_posted_by:
                        # handles: 'broker', 'broker_property', 'broker_propert' (truncated)
                        posted_by_label = "broker"
                    else:
                        posted_by_label = raw_posted_by.replace("_", " ") or "N/A"

                    prop_type = (p.get("propertyType") or "").lower()

                    # Build the size/config field based on property type
                    # so the AI never sees "NoneHK" or "None BHK" for PG/commercial
                    if prop_type == "paid_guest":
                        size_info = (
                            f"Type: paid_guest | "
                            f"Occupancy: {p.get('occupancy') or 'N/A'} | "
                            f"Gender: {p.get('gender') or 'any'}"
                        )
                    elif prop_type == "commercial":
                        size_info = (
                            f"Type: commercial | "
                            f"Sq.ft: {p.get('sq_ft') or 'N/A'}"
                        )
                    else:
                        bhk = p.get("bhk")
                        size_info = (
                            f"Type: residential | "
                            f"{bhk} BHK" if bhk else "Type: residential"
                        )

                    prop_text += (
                        f"- {p.get('title')} | {p.get('location')} | "
                        f"{format_price(p)} | {size_info} | "
                        f"{p.get('furnished')} | "
                        f"Metro: {p.get('near_metro')} | "
                        f"Bachelor: {p.get('bachelor_friendly')} | "
                        f"Family: {p.get('family_friendly')} | "
                        f"Posted by: {posted_by_label}\n"
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
            if filters.get("owner_type"):
                parts.append(f"Owner type: {filters['owner_type']}")
            filter_text = "\nFilters applied: " + ", ".join(parts)

        # =====================================================================
        # Geo Context
        #
        # CRITICAL: We explicitly tell the LLM whether properties were actually
        # found in the nearby areas or not. Without this, the LLM hallucinates
        # listings just because nearby area names are mentioned.
        #
        # "properties_found: YES"  → LLM may present them
        # "properties_found: NO"   → LLM must say no results, not invent any
        # =====================================================================
        geo_text = ""
        if geo_original_location:
            properties_found_flag = "YES" if properties else "NO"

            if geo_expanded_areas:
                # NOTE: geo_expanded_areas / dist_lookup still carry
                # distance_km internally — GeoExpander and RankingEngine
                # keep using it to sort areas/properties nearest-first, that
                # part is unaffected. What changed is that the km figure is
                # no longer written into the text handed to the LLM, so it
                # can't surface a distance number in the reply — areas are
                # named plainly instead.
                if isinstance(geo_expanded_areas[0], dict):
                    nearby_str = ", ".join(
                        r["area"] for r in geo_expanded_areas
                    )
                else:
                    nearby_str = ", ".join(geo_expanded_areas)

                # Build a precise list of which areas the shown properties
                # actually belong to (plain names, no distance attached).
                areas_with_props_str = ""
                if properties:
                    seen_areas = {}
                    for p in properties:
                        area_raw = (
                            p.get("locality") or
                            p.get("location") or
                            p.get("city") or ""
                        ).strip()
                        if not area_raw:
                            continue
                        area_lower = area_raw.lower()
                        if area_lower in seen_areas:
                            continue
                        seen_areas[area_lower] = area_raw.title()
                    areas_with_props_str = ", ".join(seen_areas.values())

                geo_text = (
                    f"\n\nGeo Search Context:"
                    f"\n  user_requested_area: {geo_original_location}"
                    f"\n  direct_listings_in_that_area: NO"
                    f"\n  nearby_areas_searched: {nearby_str}"
                    f"\n  properties_found_in_nearby_areas: {properties_found_flag}"
                    + (f"\n  areas_where_properties_were_found: {areas_with_props_str}" if areas_with_props_str else "")
                    + f"\n\nRULES based on above:"
                    f"\n  IF properties_found_in_nearby_areas = YES:"
                    f"\n    → Acknowledge no direct listings in {geo_original_location}."
                    f"\n    → Name ONLY the areas listed in 'areas_where_properties_were_found' above."
                    f"\n    → Do NOT mention any other nearby area — only the ones with actual listings."
                    f"\n    → Do NOT mention distance or km — just name the area, nothing else."
                    f"\n    → Example: 'I don't have anything directly in Virugambakkam,"
                    f" but KK Nagar is nearby and has a couple of good options.'"
                    f"\n  IF properties_found_in_nearby_areas = NO:"
                    f"\n    → Say there are no listings in {geo_original_location} or"
                    f" any of its nearby areas right now."
                    f"\n    → DO NOT name any specific nearby area as having listings."
                    f"\n    → Suggest checking back later or trying a different area."
                )
            else:
                geo_text = (
                    f"\n\nGeo Search Context:"
                    f"\n  user_requested_area: {geo_original_location}"
                    f"\n  direct_listings_in_that_area: NO"
                    f"\n  nearby_areas_searched: none found nearby"
                    f"\n  properties_found_in_nearby_areas: NO"
                    f"\n\nRULE: Say no listings in {geo_original_location} or"
                    f" nearby areas right now. Suggest checking back later."
                )

        # =====================================================================
        # Owner-Type Supply Summary
        # Always show counts when we have them so the AI can mention them
        # naturally (e.g. "There are 4 direct owner and 2 broker listings here")
        #
        # BUG FIX (root cause of the Ambattur hallucination): this block used
        # to contain ONLY the direct_owner/broker counts — no location at
        # all — even though prompts.py's RESPONSE_SYSTEM_PROMPT explicitly
        # instructs the LLM to "Read the Area: field from that block" for
        # the location name to use in its sentence. With no Area field to
        # read, the LLM fell back on the prompt's few-shot example area name
        # instead, and stated a real (but wrong) location with full
        # confidence. We now always include the Area field. If no area name
        # is available at the call site, we explicitly say so rather than
        # silently omitting the field — the prompt's fallback rule then
        # tells the LLM to use generic phrasing ("in this area") instead of
        # guessing, so the failure mode is "vague" instead of "wrong".
        # =====================================================================
        owner_counts_text = ""
        if owner_type_counts and isinstance(owner_type_counts, dict):
            d = owner_type_counts.get("direct_owner", 0)
            b = owner_type_counts.get("broker", 0)
            if d > 0 or b > 0:
                area_line = owner_type_area.strip() if owner_type_area and owner_type_area.strip() else "(not available — do not name a specific area)"
                owner_counts_text = (
                    f"\n\nOwner Type Summary for this location:"
                    f"\n  Area: {area_line}"
                    f"\n  Direct owner listings: {d}"
                    f"\n  Broker listings: {b}"
                    f"\n  (Mention these counts naturally if relevant to the user's query.)"
                )

        return (
            f"User message: {query}\n"
            f"Detected intent: {intent}"
            f"{filter_text}"
            f"{prop_text}"
            f"{owner_counts_text}"
            f"{geo_text}\n\n"
            f"Respond naturally as Tolet AI."
        )

    # ===================================
    # Trim messages to token budget
    # ===================================
    def trim_to_budget(
        self,
        messages: list,
        max_messages: int = 20
    ) -> list:

        if len(messages) <= max_messages:
            return messages

        system  = messages[0]
        rest    = messages[1:]
        trimmed = rest[-(max_messages - 1):]

        return [system] + trimmed