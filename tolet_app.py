import uuid
import streamlit as st
import requests

st.set_page_config(
    page_title="Tolet AI",
    layout="wide"
)

st.title("Tolet AI")
st.caption("Conversational Rental AI Assistant")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

with st.expander("Sample Queries"):
    st.markdown("""
- Need 2bhk in Avadi under 20k
- Show furnished apartments
- Bachelor friendly flat near metro
- ennaku 2bhk avadi la venum
- Which one is best for family?
- Any cheaper options?
- How can I contact owner?
- Need PG in Velachery
- Family house in Tambaram
- Budget flat near metro
- 2bhk in thirumulaivoyal  *(spell-corrected automatically)*
- Flat in velacery          *(spell-corrected automatically)*
""")


def render_property_card(property_item):
    image_url = property_item.get("image", "")
    if image_url:
        st.image(image_url, use_container_width=True)
    else:
        st.markdown(
            "<div style='background:#f0f2f6;height:160px;border-radius:8px;"
            "display:flex;align-items:center;justify-content:center;"
            "font-size:40px;margin-bottom:8px'>🏠</div>",
            unsafe_allow_html=True
        )

    title = property_item.get("title", "Property")
    st.subheader(title)

    price = property_item.get("price", 0)
    st.markdown(f"### Rs.{price:,}/month")

    locality = property_item.get("locality", "")
    city     = property_item.get("city", "")
    location = f"{locality}, {city}" if locality and city else locality or city
    if location:
        st.write(f"Location: {location}")

    st.divider()

    bhk       = property_item.get("bhk", "")
    prop_type = property_item.get("property_type", "")
    furnished = property_item.get("furnished", "")
    sq_ft     = property_item.get("sq_ft", "")

    col1, col2 = st.columns(2)
    with col1:
        if bhk:
            st.write(f"**{bhk} BHK**")
        if prop_type:
            st.write(prop_type)
    with col2:
        if furnished:
            st.write(furnished)
        if sq_ft:
            st.write(f"{sq_ft} sq.ft")

    floor        = property_item.get("floor", None)
    total_floors = property_item.get("total_floors", None)
    bathroom     = property_item.get("bathroom_count", None)
    balcony      = property_item.get("balcony_count", None)

    col3, col4 = st.columns(2)
    with col3:
        if floor is not None and total_floors:
            st.write(f"Floor {floor}/{total_floors}")
        if bathroom:
            st.write(f"{bathroom} Bath")
    with col4:
        if balcony:
            st.write(f"{balcony} Balcony")

    near_metro  = property_item.get("near_metro", False)
    if near_metro:
        st.write("Near Metro")

    available_from = property_item.get("available_from", "")
    if available_from:
        st.write(f"Available: {available_from}")

    st.divider()

    security  = property_item.get("security_deposit", "")
    maint     = property_item.get("maintenance", 0)
    notice    = property_item.get("notice_period", "")
    no_broker = property_item.get("no_broker", False)

    if security:
        st.write(f"Deposit: {security}")
    if maint:
        st.write(f"Maintenance: Rs.{maint:,}")
    if notice:
        st.write(f"Notice: {notice}")
    if no_broker:
        st.success("No Broker")

    amenities = property_item.get("amenities", [])
    if amenities:
        st.write("**Amenities:**")
        st.write("  •  " + "  •  ".join(amenities))

    pets = property_item.get("pets_allowed", "")
    if pets:
        st.write(f"Pets: {pets}")


def render_owner_type_cards(direct_owner_summary, broker_summary):
    """Render direct owner and broker as two separate side-by-side cards."""
    if not direct_owner_summary and not broker_summary:
        return

    col_a, col_b = st.columns(2)

    with col_a:
        if direct_owner_summary:
            st.markdown(
                f"""
                <div style='
                    background: #f0faf3;
                    border: 1.5px solid #34a853;
                    border-radius: 14px;
                    padding: 18px 20px;
                    margin-top: 14px;
                '>
                    <div style='
                        font-size: 11px;
                        font-weight: 700;
                        letter-spacing: 1.2px;
                        color: #1e7e34;
                        text-transform: uppercase;
                        margin-bottom: 8px;
                    '>Direct Owner</div>
                    <div style='
                        font-size: 14px;
                        color: #1a3a22;
                        line-height: 1.6;
                        font-weight: 500;
                    '>{direct_owner_summary.replace(chr(10), '<br>')}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                """
                <div style='
                    background: #f9f9f9;
                    border: 1.5px dashed #ccc;
                    border-radius: 14px;
                    padding: 18px 20px;
                    margin-top: 14px;
                    color: #999;
                    font-size: 13px;
                '>
                    <div style='font-size:11px;font-weight:700;letter-spacing:1.2px;
                        text-transform:uppercase;margin-bottom:8px;color:#bbb'>
                        Direct Owner
                    </div>
                    No direct owner data available.
                </div>
                """,
                unsafe_allow_html=True
            )

    with col_b:
        if broker_summary:
            st.markdown(
                f"""
                <div style='
                    background: #fffdf0;
                    border: 1.5px solid #f5a623;
                    border-radius: 14px;
                    padding: 18px 20px;
                    margin-top: 14px;
                '>
                    <div style='
                        font-size: 11px;
                        font-weight: 700;
                        letter-spacing: 1.2px;
                        color: #856404;
                        text-transform: uppercase;
                        margin-bottom: 8px;
                    '>Broker</div>
                    <div style='
                        font-size: 14px;
                        color: #3d2e00;
                        line-height: 1.6;
                        font-weight: 500;
                    '>{broker_summary.replace(chr(10), '<br>')}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                """
                <div style='
                    background: #f9f9f9;
                    border: 1.5px dashed #ccc;
                    border-radius: 14px;
                    padding: 18px 20px;
                    margin-top: 14px;
                    color: #999;
                    font-size: 13px;
                '>
                    <div style='font-size:11px;font-weight:700;letter-spacing:1.2px;
                        text-transform:uppercase;margin-bottom:8px;color:#bbb'>
                        Broker
                    </div>
                    No broker data available.
                </div>
                """,
                unsafe_allow_html=True
            )


# ===================================
# Chat History Renderer
# ===================================
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        if (
            message["role"] == "assistant"
            and "properties" in message
            and message["properties"]
        ):
            cols = st.columns(3)
            for index, property_item in enumerate(message["properties"]):
                with cols[index % 3]:
                    render_property_card(property_item)

        if message["role"] == "assistant":
            render_owner_type_cards(
                message.get("direct_owner_summary", ""),
                message.get("broker_summary", "")
            )


query = st.chat_input("Ask your rental query...")

if query:
    st.session_state.messages.append({
        "role":    "user",
        "content": query
    })

    with st.chat_message("user"):
        st.markdown(query)

    try:
        response = requests.post(
            "http://127.0.0.1:8000/api/chat",
            json={
                "session_id": st.session_state.session_id,
                "query":      query
            }
        )

        data        = response.json()
        result      = data.get("data") or {}
        ai_response = (
            result.get("response")
            or data.get("message")
            or "Something went wrong. Please try again."
        )
        properties           = result.get("properties", [])
        owner_type_counts    = result.get("owner_type_counts", {})
        direct_owner_summary = result.get("direct_owner_summary", "")
        broker_summary       = result.get("broker_summary", "")
        location             = result.get("location", "this area")

    except Exception as error:
        ai_response          = f"Backend Connection Error: {error}"
        properties           = []
        owner_type_counts    = {}
        direct_owner_summary = ""
        broker_summary       = ""
        location             = "this area"

    with st.chat_message("assistant"):
        st.markdown(ai_response)

        if properties:
            cols = st.columns(3)
            for index, property_item in enumerate(properties):
                with cols[index % 3]:
                    render_property_card(property_item)

        render_owner_type_cards(direct_owner_summary, broker_summary)

    st.session_state.messages.append({
        "role":                 "assistant",
        "content":              ai_response,
        "properties":           properties,
        "owner_type_counts":    owner_type_counts,
        "location":             location,
        "direct_owner_summary": direct_owner_summary,
        "broker_summary":       broker_summary,
    })