import streamlit as st
import requests 
import uuid

url = "http://127.0.0.1:8000/api/chat_tolu"

st.set_page_config(layout="wide")

img_col, text_col = st.columns([1, 10], vertical_alignment="center")

with img_col:

    st.image("logo.jpeg", width=70)

with text_col:

    st.markdown(
        """
        <h1 style="margin-bottom: 0rem; padding-bottom: 0rem; font-size: 2.2rem">Tolu From Tolet.city</h1>
        <h4 style="margin-top: 0.2rem; color: #6b7280; font-weight: normal; font-size: 1.1rem">An customer care support agent.</h4>
        """,
        unsafe_allow_html=True
    )

st.divider()

if "messages" not in st.session_state:

    st.session_state.messages = [
        {"role":"assistant", "content":"Hello, I'm Tolu from tolet.city, how can i help you today?"}
    ]

for msg in st.session_state.messages:

    if msg["role"] =="assistant":

        with st.chat_message("assistant", avatar="logo.jpeg"):
            st.write(msg["content"])

    else:

        with st.chat_message("user", avatar="🧑"):
            st.write(msg["content"])


if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4)

if user_prompt := st.chat_input("Ask Tolu for customer care support!"):

    with st.chat_message("user", avatar="🧑"):
        st.write(user_prompt)

    st.session_state.messages.append({"role" : "user", "content" : user_prompt})

    data = {
        "conversation_id" : st.session_state.conversation_id,
        "message" : user_prompt
    }

    response = requests.post(
        url,
        json=data
    )

    result = response.json()

    bot_reply = result["reply"]                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                

    with st.chat_message("assistant", avatar="logo.jpeg"):
        st.write(bot_reply)

    st.session_state.messages.append({"role" : "assistant", "content" : bot_reply})