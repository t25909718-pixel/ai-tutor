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

import functools
import json
import os
import re
import time

import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel

# Tools + teaching prompt ellam Gemini CLI version-la irundhu reuse pannrom
from tutor_agent_gemini import (
    MAX_TOOL_CALLS,
    MODEL,
    NOTES_DIR,
    SYSTEM,
    USE_SUPABASE,
    get_progress,
    load_history,
    save_progress,
    search_notes,
)

st.set_page_config(page_title="AI Tutor", page_icon="🎓", layout="centered")
os.makedirs(NOTES_DIR, exist_ok=True)


# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🎓 AI Personal Tutor")

    # Key order: Streamlit Cloud Secrets -> env variable -> sidebar-la type pannradhu
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
    except Exception:  # local-a secrets file illana
        secret_key = None
    api_key = secret_key or os.environ.get("GEMINI_API_KEY") or st.text_input(
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
        try:
            history = load_history(student, limit=5)
        except Exception:
            history = []
            st.caption("⚠️ Progress load aagala")
        if history:
            for h in reversed(history):
                weak = ", ".join(h["weak_points"]) or "—"
                st.markdown(f"**{h['topic']}** · {h['score']}  \n<small>{h['date']} · weak: {weak}</small>",
                            unsafe_allow_html=True)
        else:
            st.caption("Quiz mudicha inga varum")
        st.caption("💾 Database-la save aagudhu" if USE_SUPABASE else "📁 Local file-la save aagudhu")

    if st.button("🔄 New chat", use_container_width=True):
        for k in ("chat", "messages", "chat_for", "client"):
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


# Busy (503) aana idhula adutha model-ku maarum. List-la mudhal model main.
# Un account-la illaadha model irundha (404), adha skip pannidum.
FALLBACK_MODELS = [MODEL, "gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite"]


@functools.wraps(save_progress)
def save_progress_tool(student_name: str, topic: str, score: str, weak_points: list[str]) -> str:
    # Model indha tool-a call pannina, indha turn-la save aagiduchu nu note pannrom
    result = save_progress(student_name, topic, score, weak_points)
    if result == "Saved.":
        st.session_state.saved_this_turn = True
    return result


class QuizResult(BaseModel):
    graded: bool  # tutor indha message-la quiz answers-a check panni score sonnucha?
    topic: str
    score: str
    weak_points: list[str]


SCORE_PATTERN = re.compile(r"\b\d{1,2}\s*(?:/|out of)\s*\d{1,2}\b", re.IGNORECASE)


def backup_save_quiz(reply: str):
    """Model save_progress call pannala na, reply-la score irundha naame extract panni save pannrom."""
    if st.session_state.get("saved_this_turn") or not SCORE_PATTERN.search(reply):
        return
    recent = st.session_state.messages[-6:] + [{"role": "assistant", "content": reply}]
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    try:
        r = st.session_state.client.models.generate_content(
            model=st.session_state.get("model", MODEL),
            contents=(
                "Below is the end of a tutoring chat. Did the tutor's LAST message grade the student's "
                "quiz answers and give a score? If yes, set graded=true and fill topic (short), score "
                "(like '2/3') and weak_points (what the student got wrong, short phrases, may be empty). "
                "If not, set graded=false and leave other fields empty.\n\n" + transcript
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QuizResult,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
                if st.session_state.get("model", MODEL).startswith("gemini-2.5")
                else types.ThinkingConfig(thinking_level="LOW"),
            ),
        )
        q = r.parsed
        if q and q.graded and q.topic and q.score:
            if save_progress(student, q.topic, q.score, q.weak_points) == "Saved.":
                st.session_state.saved_this_turn = True
    except Exception as e:  # backup fail aanaalum chat nikkaadhu
        print("backup save failed:", e)


def make_config(model):
    progress = get_progress(student)
    # SPEED: thinking kammi. 2.5 models thinking_budget use pannum, 3.x thinking_level.
    if model.startswith("gemini-2.5"):
        thinking = types.ThinkingConfig(thinking_budget=0)
    else:
        thinking = types.ThinkingConfig(thinking_level="LOW")
    return types.GenerateContentConfig(
        system_instruction=SYSTEM
        + f"\n\nThe student's name is {student}."
        + f"\nTheir past progress (already loaded, do NOT call get_progress): {progress}"
        + "\nIMPORTANT: Whenever you tell the student their quiz score, call save_progress in that same turn.",
        thinking_config=thinking,
        tools=[save_progress_tool, search_notes],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=MAX_TOOL_CALLS
        ),
    )


def new_chat(model=MODEL, history=None):
    # Client-a session_state-la vechukkanum. Local variable-a irundha Python adha
    # garbage collect panni close pannidum -> "client has been closed" error varum.
    if "client" not in st.session_state:
        # SDK-oda silent retry off (attempts=1): busy-na udane namma fallback model-ku maarum
        st.session_state.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
    st.session_state.model = model
    return st.session_state.client.chats.create(
        model=model, config=make_config(model), history=history or []
    )


# Student illa key maarina pudhu chat start pannu
if st.session_state.get("chat_for") != (student, api_key) or "client" not in st.session_state:
    st.session_state.pop("client", None)
    st.session_state.chat = new_chat()
    st.session_state.messages = []
    st.session_state.chat_for = (student, api_key)

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
        reply, last_error = None, ""
        st.session_state.saved_this_turn = False
        # Busy-a irundha: ella models-um try pannum, 2 round (nadula 3 sec wait)
        for attempt in range(2):
            missing_models = st.session_state.setdefault("missing_models", set())
            for model in FALLBACK_MODELS:
                if model in missing_models:
                    continue
                if model != st.session_state.get("model"):
                    # Vera model-ku maarum bodhu ippo varaikkum pesuna history-a kooda eduthuttu pogum
                    st.session_state.chat = new_chat(model, st.session_state.chat.get_history())
                got_text = []

                def stream():
                    for chunk in st.session_state.chat.send_message_stream(prompt):
                        if chunk.text:
                            got_text.append(chunk.text)
                            yield chunk.text

                try:
                    reply = st.write_stream(stream()) or "..."
                    break
                except Exception as e:
                    last_error = str(e)
                    # Busy (503) illa free limit (429) -> adutha model try pannum (ovvoru model-kkum thaniya limit)
                    busy = any(x in last_error for x in ("503", "UNAVAILABLE", "overloaded", "high demand", "429", "RESOURCE_EXHAUSTED"))
                    missing = "404" in last_error or "NOT_FOUND" in last_error
                    if missing:
                        missing_models.add(model)
                    if got_text or not (busy or missing):
                        break  # vera maari error -> keezha kaattuvom
            if reply or not any(x in last_error for x in ("503", "UNAVAILABLE", "high demand")):
                break
            time.sleep(3)

        if reply and st.session_state.get("model", MODEL) != MODEL:
            st.caption(f"⚡ Main model busy, {st.session_state.model} vechu answer pannen")
        if reply:
            backup_save_quiz(reply)  # model save marandhaalum score database-ku pogum
            if st.session_state.get("saved_this_turn"):
                st.caption("💾 Quiz result save aagiduchu")
        if not reply:
            msg = last_error
            if "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg:
                reply = "😓 Google servers ippo romba busy da. 1-2 nimisham kazhichu thirumba kelu."
            elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                reply = "⏳ Free limit hit aagiduchu da. Oru nimisham wait panni thirumba kelu."
            elif "API key" in msg or "401" in msg or "403" in msg:
                reply = "🔑 API key thappu pola. Check panni thirumba podu."
            else:
                reply = f"⚠️ Error: {msg}"
            st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()  # sidebar progress update aaga
