# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

# Hardcoded GCP Project ID as requested to prevent Agent Platform project number resolution issues
PROJECT_ID = "qwiklabs-gcp-02-82f554a728eb"
BUCKET_NAME = "fitpulse-assets-qwiklabs-gcp-02-82f554a728eb"

# A2UI System Prompt Generation (v0.8 with Basic Catalog)
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are FitPulse AI, an expert workout coach. Help users design"
        " fitness plans, log workout sessions, search exercise catalog, view"
        " history, calculate strength metrics like 1RM and volume, and search"
        " public exercise databases. Use recalled facts and user preferences from"
        " memory to personalize responses."
    ),
    workflow_description=(
        "Analyze the request and return structured UI when appropriate."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text"
        " rows. Never nest a Card inside a Card. Use ONLY these components: Card,"
        " Column, Row, Text, and Image. Do not use Table or Heading"
        " (unsupported), or Buttons, actions, or forms (they do nothing in adk"
        " web). You may include one Image component, but only when you have a"
        " public https URL for the image (for example the URL an image tool"
        " returns after uploading to a public bucket). Set the Image url to"
        " that exact https link, for example"
        ' {"Image": {"url": {"literalString": "https://..."}}}. Never point an'
        " Image at a bare filename, an artifact name, or a non-http(s) path. If"
        " you do not have a public URL, add a short Text line noting the image"
        " instead. No markdown in text; use the usageHint property (\'h1\',"
        " \'h2\', \'body\') for headings and emphasis. Output ONLY the raw A2UI"
        " JSON array — no prose, and never wrap it in <a2a_datapart_json> tags"
        " or \'kind\'/\'data\'/\'metadata\' objects."
    ),
    include_schema=True,
    include_examples=True,
)

# Load Agent Engine resource name from deployment_metadata.json for Python code sandbox execution & Memory Bank
metadata_file = Path(__file__).parent.parent / "deployment_metadata.json"
agent_engine_resource_name = "projects/506723502048/locations/us-east1/reasoningEngines/8953567276561334272"
if metadata_file.exists():
    try:
        with open(metadata_file) as f:
            meta = json.load(f)
            if meta.get("remote_agent_runtime_id"):
                agent_engine_resource_name = meta.get("remote_agent_runtime_id")
    except Exception:
        pass

sandbox_code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


# WRITE: Memory Bank extraction callback triggered after every agent turn
async def generate_memories_callback(callback_context: CallbackContext):
    try:
        await callback_context.add_session_to_memory()
    except Exception:
        pass
    return None




def _get_db():
    return firestore.Client(project=PROJECT_ID)


def get_exercise_catalog(query: str = "") -> str:
    """Retrieves exercises from the exercise library catalog in Firestore.

    Args:
        query: Optional string to filter by muscle group, category, or exercise name (e.g. 'Chest', 'Legs', 'Bench').

    Returns:
        A list of matching exercises from the catalog.
    """
    db = _get_db()
    docs = db.collection("exercises").stream()
    results = []
    q = query.lower().strip()
    for doc in docs:
        data = doc.to_dict()
        if not q or any(q in str(data.get(k, "")).lower() for k in ["name", "target_muscle", "category"]):
            results.append(data)
    if not results:
        return f"No exercises found matching '{query}'."
    return str(results)


def log_workout_session(exercise_name: str, sets: int, reps: int, weight_lbs: float, notes: str = "") -> str:
    """Logs a completed workout session to Firestore.

    Args:
        exercise_name: Name of the exercise performed (e.g. 'Barbell Bench Press').
        sets: Number of sets completed.
        reps: Reps completed per set.
        weight_lbs: Weight used in lbs.
        notes: Optional notes on performance or feeling.

    Returns:
        Confirmation message with logged session ID.
    """
    db = _get_db()
    today_str = datetime.date.today().isoformat()
    session_id = f"session_{int(datetime.datetime.now().timestamp())}"
    data = {
        "session_id": session_id,
        "date": today_str,
        "exercise_name": exercise_name,
        "sets": sets,
        "reps": reps,
        "weight_lbs": weight_lbs,
        "notes": notes
    }
    db.collection("workout_sessions").document(session_id).set(data)
    return f"Successfully logged workout session {session_id} for {exercise_name} ({sets}x{reps} @ {weight_lbs} lbs)."


def get_workout_history(limit: int = 5) -> str:
    """Retrieves past logged workout sessions from Firestore.

    Args:
        limit: Maximum number of recent workout sessions to retrieve (default: 5).

    Returns:
        A list of recent workout sessions logged by the user.
    """
    db = _get_db()
    docs = db.collection("workout_sessions").limit(limit).stream()
    history = [doc.to_dict() for doc in docs]
    if not history:
        return "No workout history logged yet."
    return str(history)


def calculate_one_rep_max_and_volume(weight_lbs: float, reps: int, sets: int = 1) -> str:
    """Calculates estimated One-Rep Max (1RM) using the Epley formula and total workout volume.

    Args:
        weight_lbs: Weight lifted in pounds.
        reps: Repetitions completed per set.
        sets: Number of sets completed (default: 1).

    Returns:
        A summary of estimated 1RM, total volume lifted, and workout metrics.
    """
    if reps <= 0 or weight_lbs <= 0:
        return "Weight and reps must be positive numbers."

    if reps == 1:
        one_rep_max = weight_lbs
    else:
        one_rep_max = weight_lbs * (1.0 + reps / 30.0)

    total_volume = sets * reps * weight_lbs

    return (
        f"Calculated Workout Metrics:\n"
        f"- Estimated 1RM (One-Rep Max): {round(one_rep_max, 1)} lbs\n"
        f"- Total Training Volume: {round(total_volume, 1)} lbs ({sets} sets x {reps} reps x {weight_lbs} lbs)"
    )


def search_public_exercise_database(query: str = "") -> str:
    """Fetches real exercise data from the free WGER Workout Manager public API.

    Args:
        query: Optional exercise name or keyword to search (e.g. 'Press', 'Curl', 'Shoulder', 'Legs').

    Returns:
        A summary list of matching exercises with categories and descriptions from the public database.
    """
    import json
    import os
    import urllib.request

    url = "https://wger.de/api/v2/exerciseinfo/?limit=30"
    headers = {
        "Accept": "application/json",
        "User-Agent": "FitPulse-Agent/1.0"
    }
    
    # Read API key from environment variable if provided
    api_key = os.environ.get("WGER_API_KEY")
    if api_key:
        headers["Authorization"] = f"Token {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        matches = []
        q = query.lower().strip()
        for item in data.get("results", []):
            category = item.get("category", {}).get("name", "General") if isinstance(item.get("category"), dict) else "General"
            translations = item.get("translations", [])
            en_trans = [t for t in translations if t.get("language") == 2]
            trans = en_trans[0] if en_trans else (translations[0] if translations else {})
            name = trans.get("name", "Unknown")
            desc = trans.get("description", "").replace("<p>", "").replace("</p>", "").replace("<ul>", "").replace("</ul>", "").replace("<li>", "").replace("</li>", " ").strip()

            if not q or q in name.lower() or q in category.lower():
                matches.append(f"- {name} (Category: {category}): {desc[:120]}..." if desc else f"- {name} (Category: {category})")

        if not matches:
            return f"No exercises found matching '{query}' in WGER public database."

        return "\n".join(matches[:5])
    except Exception as e:
        return f"Public exercise API request failed: {e}"


async def generate_workout_demonstration_video(
    prompt: str, tool_context: ToolContext
) -> str:
    """Generates a short workout demonstration video using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the generated video to the ADK Playground Artifacts panel and uploads the video bytes directly to Cloud Storage.

    Args:
        prompt: Detailed description of the workout exercise or form demonstration to generate (e.g. 'A person performing a dumbbell bicep curl').
        tool_context: ADK ToolContext for artifact management.

    Returns:
        The public HTTPS GCS URL of the generated video (https://storage.googleapis.com/<bucket>/<object>).
    """
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="global",
    )

    interaction = client.interactions.create(
        model="gemini-omni-flash-preview",
        input=f"A short 3-second exercise form demonstration video: {prompt}",
    )

    video_bytes = None
    if hasattr(interaction, "output_video") and interaction.output_video:
        data = getattr(interaction.output_video, "data", None)
        if isinstance(data, bytes):
            video_bytes = data
        elif isinstance(data, str):
            video_bytes = base64.b64decode(data)

    if not video_bytes and hasattr(interaction, "steps"):
        for step in getattr(interaction, "steps", []) or []:
            for item in getattr(step, "content", []) or []:
                if getattr(item, "type", None) == "video" or getattr(
                    item, "mime_type", ""
                ).startswith("video"):
                    d = getattr(item, "data", None)
                    if isinstance(d, bytes):
                        video_bytes = d
                    elif isinstance(d, str):
                        video_bytes = base64.b64decode(d)

    if not video_bytes:
        raise ValueError("No video data returned from gemini-omni-flash-preview model.")

    file_id = f"workout_demo_{uuid.uuid4().hex[:8]}.mp4"

    # 1. Save artifact to ADK Playground Artifacts panel
    part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
    await tool_context.save_artifact(filename=file_id, artifact=part)

    # 2. Upload video bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_id)
    blob.upload_from_string(video_bytes, content_type="video/mp4")

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{file_id}"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    tools=[
        PreloadMemoryTool(),
        get_exercise_catalog,
        log_workout_session,
        get_workout_history,
        calculate_one_rep_max_and_volume,
        search_public_exercise_database,
        generate_workout_demonstration_video,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
    code_executor=sandbox_code_executor,
)

app = App(
    root_agent=root_agent,
    name="app",
)
