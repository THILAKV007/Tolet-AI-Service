import uuid
import streamlit as st
import requests


st.set_page_config(
    page_title="Tolet AI",
    layout="wide"
)

st.title("🏠 Tolet AI")
st.caption("Conversational Rental AI Assistant")


# ===================================
# SESSION ID — unique per browser tab
# ===================================
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []


# ===================================
# Sample Queries
# ===================================
with st.expander("💡 Sample Queries"):
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
""")


# ===================================
# Property Card Renderer
# Uses actual schema fields from
# the serialized property dict
# ===================================
def render_property_card(property_item):

    # ── Image ──────────────────────
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

    # ── Title ──────────────────────
    title = property_item.get("title", "Property")
    st.subheader(title)

    # ── Price (prominent) ──────────
    price = property_item.get("price", 0)
    st.markdown(f"### ₹{price:,}/month")

    # ── Location ───────────────────
    locality = property_item.get("locality", "")
    city     = property_item.get("city", "")
    location = f"{locality}, {city}" if locality and city else locality or city
    if location:
        st.write(f"📍 {location}")

    st.divider()

    # ── Core Details ───────────────
    bhk          = property_item.get("bhk", "")
    prop_type    = property_item.get("property_type", "")
    furnished    = property_item.get("furnished", "")
    sq_ft        = property_item.get("sq_ft", "")

    col1, col2 = st.columns(2)
    with col1:
        if bhk:
            st.write(f"🛏️ **{bhk} BHK**")
        if prop_type:
            st.write(f"🏢 {prop_type}")
    with col2:
        if furnished:
            st.write(f"🛋️ {furnished}")
        if sq_ft:
            st.write(f"📐 {sq_ft} sq.ft")

    # ── Floor Info ─────────────────
    floor        = property_item.get("floor", None)
    total_floors = property_item.get("total_floors", None)
    bathroom     = property_item.get("bathroom_count", None)
    balcony      = property_item.get("balcony_count", None)

    col3, col4 = st.columns(2)
    with col3:
        if floor is not None and total_floors:
            st.write(f"🏗️ Floor {floor}/{total_floors}")
        if bathroom:
            st.write(f"🚿 {bathroom} Bath")
    with col4:
        if balcony:
            st.write(f"🌿 {balcony} Balcony")

    # ── Metro & Tenant ─────────────
    near_metro  = property_item.get("near_metro", False)
    tenant_type = property_item.get("apartment_type", "")

    if near_metro:
        st.write("🚇 Near Metro")

    # ── Availability ───────────────
    available_from = property_item.get("available_from", "")
    if available_from:
        st.write(f"📅 Available: {available_from}")

    st.divider()

    # ── Financial Details ──────────
    security  = property_item.get("security_deposit", "")
    maint     = property_item.get("maintenance", 0)
    notice    = property_item.get("notice_period", "")
    no_broker = property_item.get("no_broker", False)

    if security:
        st.write(f"🔒 Deposit: {security}")
    if maint:
        st.write(f"🔧 Maintenance: ₹{maint:,}")
    if notice:
        st.write(f"📋 Notice: {notice}")
    if no_broker:
        st.success("✅ No Broker")

    # ── Amenities ──────────────────
    amenities = property_item.get("amenities", [])
    if amenities:
        st.write("✨ **Amenities:**")
        st.write("  •  " + "  •  ".join(amenities))

    # ── Pets ───────────────────────
    pets = property_item.get("pets_allowed", "")
    if pets:
        icon = "🐾" if pets.lower() == "yes" else "🚫"
        st.write(f"{icon} Pets: {pets}")


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


# ===================================
# Chat Input & API Call
# ===================================
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
        result      = data.get("data") or {}          # fix: `or {}` handles data=None
        ai_response = (
            result.get("response")
            or data.get("message")
            or "Something went wrong. Please try again."
        )
        properties  = result.get("properties", [])

    except Exception as error:
        ai_response = f"Backend Connection Error: {error}"
        properties  = []

    with st.chat_message("assistant"):
        st.markdown(ai_response)

        if properties:
            cols = st.columns(3)
            for index, property_item in enumerate(properties):
                with cols[index % 3]:
                    render_property_card(property_item)

    st.session_state.messages.append({
        "role":       "assistant",
        "content":    ai_response,
        "properties": properties
    })