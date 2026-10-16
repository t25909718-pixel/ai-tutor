"""
AI Personal Tutor - Streamlit Web App (Gemini free tier)
---------------------------------------------------------
Indha file-um tutor_agent_gemini.py-um ORE folder-la irukkanum.

Setup:
    pip install streamlit google-genai
    export GEMINI_API_KEY="un-key"      (Windows: set GEMINI_API_KEY=un-key)
    streamlit run app.py

Browser-la http://localhost:8501 open aagum.
Same WiFi-la irukkura friends-um "Network URL" vechu open pannalam.
"""

import json
import os

import streamlit as st
from google import genai
from google.genai import types

# Tools + teaching prompt ellam Gemini CLI version-la irundhu reuse pannrom
from tutor_agent_gemini import (
    MAX_TOOL_CALLS,
    MODEL,
    NOTES_DIR,
    SYSTEM,
    _load_progress,
    get_progress,
    save_progress,
    search_notes,
)

st.set_page_config(page_title="AI Tutor", page_icon="🎓", layout="centered")
os.makedirs(NOTES_DIR, exist_ok=True)


# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🎓 AI Personal Tutor")

    api_key = os.environ.get("GEMINI_API_KEY") or st.text_input(
        "Gemini API key", type="password", help="aistudio.google.com/apikey-la free-a edu"
    )
    student = st.text_input("Un peru", placeholder="e.g. Tamil")

    st.divider()
    st.subheader("📚 Un notes")
    uploads = st.file_uploader(
        "Syllabus notes (.txt / .md)", type=["txt", "md"], accept_multiple_files=True
    )
    for f in uploads or []:
        with open(os.path.join(NOTES_DIR, os.path.basename(f.name)), "wb") as out:
            out.write(f.getbuffer())
    saved = sorted(os.listdir(NOTES_DIR))
    st.caption(", ".join(saved) if saved else "Innum notes upload pannala")

    if student:
        st.divider()
        st.subheader("📈 Un progress")
        history = _load_progress().get(student.strip().lower(), [])
        if history:
            for h in reversed(history[-5:]):
                weak = ", ".join(h["weak_points"]) or "—"
                st.markdown(f"**{h['topic']}** · {h['score']}  \n<small>{h['date']} · weak: {weak}</small>",
                            unsafe_allow_html=True)
        else:
            st.caption("Quiz mudicha inga varum")

    if st.button("🔄 New chat", use_container_width=True):
        for k in ("chat", "messages", "chat_for"):
            st.session_state.pop(k, None)
        st.rerun()


# ---------------- Main chat ----------------
st.title("🎓 Un Personal Tutor")

if not api_key:
    st.info("Left side-la Gemini API key podu (illa GEMINI_API_KEY env variable set pannu).")
    st.stop()
if not student:
    st.info("Left side-la un peru type pannu, apram start pannalam 👋")
    st.stop()


def new_chat():
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM + f"\n\nThe student's name is {student}.",
        tools=[get_progress, save_progress, search_notes],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=MAX_TOOL_CALLS
        ),
    )
    return client.chats.create(model=MODEL, config=config)


# Student maarina pudhu chat start pannu
if st.session_state.get("chat_for") != student:
    st.session_state.chat = new_chat()
    st.session_state.messages = []
    st.session_state.chat_for = student

if not st.session_state.messages:
    st.markdown(
        f"Vanakkam **{student}**! Enna topic padikkanum? 😊  \n"
        "Example: *Recursion explain pannu*, *Ohm's law-la quiz vei*, *Indha problem-ku hint kudu*"
    )

for m in st.session_state.messages:
    with st.chat_message(m["role"], avatar="🧑‍🎓" if m["role"] == "user" else "🎓"):
        st.markdown(m["content"])

if prompt := st.chat_input("Un doubt-a type pannu..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍🎓"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🎓"):
        with st.spinner("Yosikkiren..."):
            try:
                reply = st.session_state.chat.send_message(prompt).text or "..."
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    reply = "⏳ Free limit hit aagiduchu da. Oru nimisham wait panni thirumba kelu."
                elif "API key" in msg or "401" in msg or "403" in msg:
                    reply = "🔑 API key thappu pola. Check panni thirumba podu."
                else:
                    reply = f"⚠️ Error: {msg}"
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()  # sidebar progress update aaga
