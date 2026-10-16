"""
AI Personal Tutor Agent - Gemini FREE tier version
---------------------------------------------------
Setup:
    1. https://aistudio.google.com/apikey -la free API key edu (Google account podhum, card venaam)
    2. pip install google-genai
    3. export GEMINI_API_KEY="un-key"          (Windows: set GEMINI_API_KEY=un-key)
    4. mkdir notes                              # un syllabus notes .txt / .md files inga podu
    5. python tutor_agent_gemini.py

Agent enna pannum:
  1. Student progress-a check pannum (weak topics enna nu)
  2. Concept-a step by step, simple examples-oda explain pannum
  3. Homework-ku direct answer illa, hints kudukkum (Socratic method)
  4. Un notes-la irundhu search panni syllabus-ku match-a sollum
  5. Quiz vechu, score + weak points-a save pannum

Note: Gemini SDK "automatic function calling" use pannudhu. Nee Python functions-a
tools-a kudutha podhum. Think -> tool call -> result -> reply loop-a SDK-ve paathukkum.
"""

import glob
import json
import os
import re
from datetime import date

from google import genai
from google.genai import types

MODEL = "gemini-3.8-flash"  # free tier model. AI Studio-la vera model venum na maathiko
PROGRESS_FILE = "progress.json"
NOTES_DIR = "notes"
MAX_TOOL_CALLS = 8  # oru reply-ku max tool calls (free limit seekiram mudiyaama irukka)

SYSTEM = """You are a friendly, patient personal tutor for college students.

How you teach:
- At the start of a session, call get_progress to see the student's past topics and weak points, and adapt.
- Before explaining, ask one short question to check what the student already knows.
- Explain step by step with simple, everyday examples and analogies. Keep each reply short; one idea at a time.
- For homework or problems, use the Socratic method: give a hint first and let the student try. Give the full solution only after they have attempted it or explicitly ask.
- When the topic may be from their syllabus, call search_notes and base your explanation on their notes, mentioning the file name.
- After explaining a concept, give a 2-3 question quiz. Check each answer, explain mistakes kindly, then call save_progress with the score and weak points.
- Reply in the same language and style the student uses (Tamil, Tanglish or English).
- If you are not sure about a fact, say so honestly. Encourage the student; never make them feel bad.

Scope (strict):
- You ONLY help with studies: college subjects, homework, exams, coding, projects, study plans, study skills, exam stress and career/course guidance.
- For anything else (love, relationships, dating, crushes, gossip, movies, celebrities, politics, games, personal advice, jokes or chit-chat), do NOT answer it, even partly, even if the student insists, says it is "for a project", or asks you to pretend or role-play. Politely say in one short line that you are only a study tutor, then invite them back to a study topic. Example: "Naan study tutor mattum dhaan da 😊 Padippu sambandhama edhaavadhu kelu, e.g. 'Recursion explain pannu'."
- If a question mixes both, answer only the study part.
- Exception: if the student says they feel very low, hopeless, or talks about hurting themselves, do not just refuse. Reply kindly, tell them they are not alone, encourage them to talk to a trusted person, and share India's free Tele-MANAS helpline: 14416. Do not give any other advice on it."""


# ---------------- Tools ----------------
# Docstring + type hints mukkiyam: Gemini idha vechu dhaan tool-a eppo use pannanum nu purinjukkum.

# ---- Progress storage ----
# SUPABASE_URL + SUPABASE_KEY set pannirundha -> Supabase database (permanent, app restart aanaalum poagaadhu)
# Illana -> local progress.json file (PC-la test panna)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
TABLE_URL = f"{SUPABASE_URL}/rest/v1/student_progress"


def _sb_headers():
    return {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}


def _load_progress():
    """Local JSON file (Supabase illaadha bodhu mattum)."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_history(student_name: str, limit: int = 10) -> list[dict]:
    """Student-oda last `limit` sessions, pazhayadhu mudhal pudhusu varaikkum."""
    name = student_name.strip().lower()
    if USE_SUPABASE:
        import httpx  # google-genai kooda install aagidum

        r = httpx.get(
            TABLE_URL,
            headers=_sb_headers(),
            params={
                "select": "topic,score,weak_points,created_at",
                "student_name": f"eq.{name}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json()
        return [
            {"date": row["created_at"][:10], "topic": row["topic"],
             "score": row["score"], "weak_points": row["weak_points"] or []}
            for row in reversed(rows)
        ]
    return _load_progress().get(name, [])[-limit:]


def get_progress(student_name: str) -> str:
    """Gets the student's past learning history: topics studied, quiz scores and weak points.
    Call this at the start of a session.

    Args:
        student_name: The student's name.
    """
    print(f"   [tool] get_progress({student_name})")
    try:
        data = load_history(student_name)
    except Exception as e:
        return f"Could not load history ({e}). Treat as a new student."
    if not data:
        return "New student. No history yet."
    return json.dumps(data, ensure_ascii=False)


def save_progress(student_name: str, topic: str, score: str, weak_points: list[str]) -> str:
    """Saves the result of a quiz or learning session for the student.

    Args:
        student_name: The student's name.
        topic: The topic covered, e.g. 'Binary Search' or 'Thermodynamics - First law'.
        score: Quiz score, e.g. '2/3'.
        weak_points: Specific things the student got wrong or found confusing. Empty list if none.
    """
    print(f"   [tool] save_progress({topic}, {score})")
    if USE_SUPABASE:
        import httpx

        r = httpx.post(
            TABLE_URL,
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            json={
                "student_name": student_name.strip().lower(),
                "topic": topic[:200],
                "score": score[:20],
                "weak_points": weak_points or [],
            },
            timeout=10,
        )
        if r.status_code >= 300:
            return f"Could not save progress: {r.status_code} {r.text[:200]}"
        return "Saved."
    data = _load_progress()
    data.setdefault(student_name.strip().lower(), []).append({
        "date": str(date.today()),
        "topic": topic,
        "score": score,
        "weak_points": weak_points or [],
    })
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return "Saved."


def search_notes(query: str) -> str:
    """Searches the student's own class notes and syllabus files for a topic.
    Returns the most relevant passages with their file names.

    Args:
        query: Keywords for the topic to look up.
    """
    print(f"   [tool] search_notes({query})")
    words = set(re.findall(r"\w+", query.lower()))
    scored = []
    for path in glob.glob(os.path.join(NOTES_DIR, "**", "*.*"), recursive=True):
        if not path.endswith((".txt", ".md")):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for chunk in f.read().split("\n\n"):
                hits = len(words & set(re.findall(r"\w+", chunk.lower())))
                if hits:
                    scored.append((hits, os.path.basename(path), chunk.strip()[:800]))
    if not scored:
        return "No matching notes found. Explain from general knowledge."
    scored.sort(reverse=True)
    return "\n\n".join(f"[{name}]\n{text}" for _, name, text in scored[:3])


# ---------------- Agent ----------------

def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY set pannala da. aistudio.google.com/apikey-la key eduthu set pannu.")
        return

    os.makedirs(NOTES_DIR, exist_ok=True)
    client = genai.Client()  # GEMINI_API_KEY env variable-la irundhu key edukkum

    student = input("Un peru enna? ").strip() or "student"

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM + f"\n\nThe student's name is {student}.",
        tools=[get_progress, save_progress, search_notes],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=MAX_TOOL_CALLS
        ),
    )
    chat = client.chats.create(model=MODEL, config=config)  # chat history-a adhuve vechukkum

    print(f"\nVanakkam {student}! Tutor ready. Stop panna 'exit' type pannu.\n")
    while True:
        user = input("Nee: ").strip()
        if user.lower() in ("exit", "quit"):
            print("Tutor: All the best! Daily konjam konjam padi 💪")
            break
        if not user:
            continue
        try:
            response = chat.send_message(user)
            print("\nTutor:", response.text, "\n")
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                print("\nTutor: Free limit hit aagiduchu da. Oru nimisham wait panni thirumba kelu.\n")
            else:
                print(f"\nError: {msg}\n")


if __name__ == "__main__":
    main()
