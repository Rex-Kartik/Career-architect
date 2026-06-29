# Import the os module, which provides a way of using operating system dependent functionality.
import os

# Import the json module, which is used for working with JSON data.
import json

# Import the 're' module for using regular expressions to clean up text.
import re

# Import time for rate-limit backoff.
import time

# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv

# Import the official Google Generative AI SDK (new `google-genai` package).
# Install with: pip install google-genai
import google.generativeai as genai

# Import the Tavily client for web search.
from tavily import TavilyClient

# --- Load Environment Variables ---
load_dotenv()

# --- CONFIGURE THE AI CLIENTS AND ADD VALIDATION ---
gemini_api_key = os.environ.get("GEMINI_API_KEY")
tavily_api_key = os.environ.get("TAVILY_API_KEY")

if not gemini_api_key or not tavily_api_key:
    raise ValueError("GEMINI_API_KEY or TAVILY_API_KEY not found. Please check your .env file.")

genai.configure(api_key=gemini_api_key)
tavily_client = TavilyClient(api_key=tavily_api_key)

# ---------------------------------------------------------------------------
# MODEL ROUTING STRATEGY (Free Tier, as of June 2026)
#
#  Model                    RPM   RPD    Best for
#  ──────────────────────── ───── ─────  ──────────────────────────────────────
#  gemini-2.5-flash-lite     30   1 500  High-volume, simple/structured tasks
#                                        (title correction, loading facts,
#                                         step-title brainstorm, JSON parsing)
#  gemini-2.5-flash          15   1 500  Moderate-complexity tasks that benefit
#                                        from better reasoning (step details,
#                                         course selection from RAG context)
#  gemini-3.1-flash-lite    varies/preview  Reserved as a fallback alias
#
# Rule of thumb applied here:
#   LITE_MODEL  → fast, cheap, many calls  → simple extraction / formatting
#   FLASH_MODEL → smarter reasoning        → tasks that synthesise/compare info
# ---------------------------------------------------------------------------
LITE_MODEL  = "gemini-2.5-flash-lite"   # 30 RPM / 1 500 RPD  – high-throughput
FLASH_MODEL = "gemini-2.5-flash"        # 15 RPM / 1 500 RPD  – better reasoning

# How many seconds to wait before retrying after a 429 / quota error.
_RATE_LIMIT_BACKOFF_SECONDS = 60


# --- HELPER FUNCTIONS -------------------------------------------------------

def call_llm(prompt: str, model: str = LITE_MODEL, json_mode: bool = False,
             retries: int = 3) -> str:
    """
    Unified helper to call the Gemini API and return response text.

    Automatically retries up to `retries` times with exponential backoff when
    a quota / rate-limit error (429) is encountered.
    """
    final_prompt = prompt
    if json_mode:
        final_prompt = (
            prompt
            + "\n\nIMPORTANT: Respond ONLY with valid JSON. "
              "No markdown, no explanation, just JSON."
        )

    gemini_model = genai.GenerativeModel(model)

    for attempt in range(1, retries + 1):
        try:
            response = gemini_model.generate_content(final_prompt)
            response_text = response.text

            if not response_text or response_text.strip() == "":
                raise ValueError("Gemini API returned an empty response.")

            return response_text

        except Exception as e:
            err_str = str(e).lower()
            is_quota = "429" in err_str or "quota" in err_str or "rate" in err_str

            if is_quota and attempt < retries:
                wait = _RATE_LIMIT_BACKOFF_SECONDS * attempt  # 60 s, 120 s, …
                print(f"  [Rate limit hit on {model}] Waiting {wait}s before retry "
                      f"(attempt {attempt}/{retries})…")
                time.sleep(wait)
            else:
                print(f"  [Gemini API error on {model}]: {e}")
                raise


def _extract_json(text: str) -> dict:
    """Robustly extract JSON from response text (handles markdown code blocks, etc.)."""
    text = text.strip()

    # Try to parse as-is first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks (```json ... ```).
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Try to extract raw JSON object/array from text.
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        end_idx = text.rfind(end_char)
        if end_idx > start_idx:
            json_str = text[start_idx:end_idx + 1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


# --- PUBLIC AI FUNCTIONS ----------------------------------------------------

def get_corrected_job_title(job_title: str) -> str:
    """
    Correct spelling and standardise the user's job-title input.

    Uses: LITE_MODEL (gemini-2.5-flash-lite)
    Rationale: Simple single-turn text correction — no reasoning required,
    benefits from flash-lite's higher RPD allowance.
    """
    print(f"AI is correcting the job title: '{job_title}'")
    try:
        prompt = (
            f"Correct any spelling mistakes in the following job title and provide "
            f"the standard, professional name for it. "
            f"Respond with ONLY the corrected job title. "
            f"Input: '{job_title}'"
        )
        response_text = call_llm(prompt, model=LITE_MODEL)
        corrected_title = response_text.strip().replace('**', '')
        print(f"AI suggested corrected title: '{corrected_title}'")
        return corrected_title
    except Exception as e:
        print(f"Error during title correction: {e}")
        return job_title


def get_loading_facts(job_title: str) -> dict:
    """
    Generate interesting loading-screen facts for a given job title.

    Uses: LITE_MODEL (gemini-2.5-flash-lite)
    Rationale: Generating 4 short facts is a low-complexity creative task that
    doesn't require deeper reasoning; flash-lite's higher throughput is ideal.
    """
    print(f" > Generating loading screen facts for '{job_title}'…")
    try:
        prompt = (
            f"For the career path of a '{job_title}', provide a JSON object with a "
            f"'facts' key containing an array of 4 short, interesting, "
            f"one-sentence facts about this career."
        )
        response_text = call_llm(prompt, model=LITE_MODEL, json_mode=True)
        return _extract_json(response_text)
    except Exception as e:
        print(f" - AI Error during loading facts generation: {e}")
        return {
            "facts": [
                "The journey to a new career is a marathon, not a sprint.",
                "Continuous learning is key to success in any field.",
                "Networking can open doors to unexpected opportunities.",
            ]
        }


# --- "ASSEMBLY LINE" HELPER FUNCTIONS ---------------------------------------

def _get_roadmap_step_titles(job_title: str) -> list:
    """
    Station 1 — Brainstormer: Return only the step titles for a career roadmap.

    Uses: LITE_MODEL (gemini-2.5-flash-lite)
    Rationale: Listing sequential milestone titles is a structured, low-complexity
    task; flash-lite handles it well and costs fewer RPD tokens.
    """
    prompt = (
        f"You are a career planner. What are the main sequential steps to become "
        f"a '{job_title}'? "
        f"Respond with ONLY a JSON object: "
        f'{{\"steps\": [\"Step 1 Title\", \"Step 2 Title\", ...]}}.'
    )
    response_text = call_llm(prompt, model=LITE_MODEL, json_mode=True)
    content = _extract_json(response_text)
    return content.get("steps", [])


def _get_details_for_step(step_title: str) -> dict:
    """
    Station 2 — Elaborator: Return description + skills for a single roadmap step.

    Uses: FLASH_MODEL (gemini-2.5-flash)
    Rationale: Writing a concise but accurate description and picking the most
    relevant skills requires decent domain knowledge and reasoning — flash is the
    right trade-off between quality and rate limits here.
    """
    prompt = (
        f"For the career step '{step_title}', provide:\n"
        f"1. A clear one-sentence description.\n"
        f"2. The 3–5 most important skills to learn.\n"
        f"Respond with ONLY a JSON object with 'description' (string) and "
        f"'skills' (array of strings) keys."
    )
    response_text = call_llm(prompt, model=FLASH_MODEL, json_mode=True)
    return _extract_json(response_text)


def _find_courses_for_step_with_focused_search(step_title: str) -> dict:
    """
    Station 3 — Focused Researcher & Selector: Use RAG (Tavily + Gemini) to
    find reliable course links for a roadmap step.

    Uses: FLASH_MODEL (gemini-2.5-flash)
    Rationale: This task involves synthesising and comparing multiple search
    results to select the single best free and paid course — exactly the kind of
    light reasoning where flash outperforms flash-lite meaningfully.
    """
    try:
        search_sites_filter = (
            "site:udemy.com/course/ OR site:coursera.org/learn/ "
            "OR site:edx.org/course/ OR site:youtube.com/playlist "
            "OR site:freecodecamp.org/learn/"
        )
        search_query = f"best '{step_title}' course {search_sites_filter}"

        context_results = tavily_client.search(query=search_query, max_results=7)
        search_context = "\n".join(
            f"URL: {res['url']}\nTitle: {res['title']}\nContent: {res['content']}"
            for res in context_results["results"]
        )

        prompt = (
            f"You are an expert course selector. Based ONLY on the provided context, "
            f"select the best free and paid course for '{step_title}'.\n"
            f"Context:\n---\n{search_context}\n---\n"
            f"Respond with ONLY a JSON object with 'free_course' and 'paid_course' keys. "
            f"Each must have 'name', a direct 'url', and a 'reason'. "
            f"If no course is found, set the value to null."
        )

        response_text = call_llm(prompt, model=FLASH_MODEL, json_mode=True)
        return _extract_json(response_text)

    except Exception as e:
        print(f" - AI Error finding courses for '{step_title}': {e}")
        return {
            "free_course":  {"name": "Not Found", "url": "#"},
            "paid_course":  {"name": "Not Found", "url": "#"},
        }


def _build_mermaid_graph(steps: list) -> str:
    """
    Final Assembly — Builder: Programmatically create a valid Mermaid graph string.

    No LLM call; pure Python string construction (zero API quota consumed).
    """
    graph_str = "graph TD\n"
    for i, step in enumerate(steps):
        clean_title = re.sub(r'[^a-zA-Z0-9\s-]', '', step['title'])
        graph_str += f" step{i}[{clean_title}]\n"
        if i > 0:
            graph_str += f" step{i - 1} --> step{i}\n"
    return graph_str


def get_ai_roadmap(job_title: str, task_id: str, task_statuses: dict) -> str:
    """
    Main orchestrator for the AI Assembly Line.

    Model usage per station:
      Station 1 (step titles)     → gemini-2.5-flash-lite  (simple list, many calls OK)
      Station 2 (step details)    → gemini-2.5-flash        (needs domain reasoning)
      Station 3 (course search)   → gemini-2.5-flash        (synthesises RAG results)
      Final assembly (graph)      → no LLM call             (pure Python)

    Rate-limit guard: a small inter-step delay is inserted to stay well within
    the 15 RPM cap of gemini-2.5-flash when iterating over many steps.
    """
    print(f"Generating roadmap for: '{job_title}' using Gemini free-tier assembly line")

    # Seconds to sleep between per-step FLASH_MODEL calls to avoid hitting 15 RPM.
    # At 15 RPM we have 4 s per request; 5 s gives comfortable headroom.
    INTER_STEP_DELAY = 5

    try:
        # --- Station 1: Brainstormer (LITE_MODEL) ---
        task_statuses[task_id] = {
            "status":   "running",
            "message":  "Brainstorming core roadmap steps…",
            "progress": 10,
        }
        step_titles = _get_roadmap_step_titles(job_title)

        if not step_titles:
            raise ValueError("AI Brainstormer failed to generate step titles.")

        full_roadmap_steps = []
        total_steps = len(step_titles)

        # --- Loop for Stations 2 & 3 ---
        for i, title in enumerate(step_titles):
            current_progress = 10 + int(80 * (i / total_steps))

            # --- Station 2: Elaborator (FLASH_MODEL) ---
            task_statuses[task_id] = {
                "status":   "running",
                "message":  f"[{i + 1}/{total_steps}] Defining skills for '{title}'…",
                "progress": current_progress,
            }
            details = _get_details_for_step(title)

            # Brief pause to respect FLASH_MODEL's 15 RPM cap.
            time.sleep(INTER_STEP_DELAY)

            # --- Station 3: Researcher (FLASH_MODEL) ---
            task_statuses[task_id] = {
                "status":   "running",
                "message":  f"[{i + 1}/{total_steps}] Searching best courses for '{title}'…",
                "progress": current_progress + int(80 / total_steps / 2),
            }
            courses = _find_courses_for_step_with_focused_search(title)

            # Another pause before the next iteration's FLASH_MODEL calls.
            time.sleep(INTER_STEP_DELAY)

            step_obj = {
                "title":       title,
                "description": details.get("description", ""),
                "skills":      details.get("skills", []),
                "free_course": courses.get("free_course"),
                "paid_course": courses.get("paid_course"),
            }
            full_roadmap_steps.append(step_obj)

        # --- Final Assembly (no LLM) ---
        task_statuses[task_id] = {
            "status":   "running",
            "message":  "Assembling the final visual graph…",
            "progress": 95,
        }
        mermaid_graph = _build_mermaid_graph(full_roadmap_steps)

        final_roadmap = {
            "roadmap":       full_roadmap_steps,
            "mermaid_graph": mermaid_graph,
        }

        return json.dumps(final_roadmap)

    except Exception as e:
        print(f"Error during roadmap generation: {e}")
        raise
