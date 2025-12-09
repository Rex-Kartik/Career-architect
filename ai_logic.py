# Import the os module, which provides a way of using operating system dependent functionality.
import os

# Import the json module, which is used for working with JSON data.
import json

# Import the 're' module for using regular expressions to clean up text.
import re

# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv

# Import Perplexity client (instead of google.generativeai)
from openai import OpenAI

# Import the Tavily client for web search
from tavily import TavilyClient

# --- Load Environment Variables ---
# This ensures that this module can always access the necessary API keys.
load_dotenv()

# --- CONFIGURE THE AI CLIENTS AND ADD VALIDATION ---
perplexity_api_key = os.environ.get("PERPLEXITY_API_KEY")
tavily_api_key = os.environ.get("TAVILY_API_KEY")

if not perplexity_api_key or not tavily_api_key:
    raise ValueError("PERPLEXITY_API_KEY or TAVILY_API_KEY not found. Please check your .env file.")

# Initialize Perplexity client using OpenAI-compatible interface
client = OpenAI(api_key=perplexity_api_key, base_url="https://api.perplexity.ai")
tavily_client = TavilyClient(api_key=tavily_api_key)

# --- CONFIGURATION ---
DEFAULT_MODEL = "sonar"  # Budget-friendly Sonar model for all tasks

# --- HELPER FUNCTION ---
def call_llm(prompt: str, model: str = DEFAULT_MODEL, json_mode: bool = False) -> str:
    """Unified helper to call Perplexity API and return response text."""
    try:
        # If JSON mode is requested, append instruction to the prompt
        final_prompt = prompt
        if json_mode:
            final_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown, no explanation, just JSON."
        
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": final_prompt}],
        )
        response_text = completion.choices[0].message.content
        
        # Validate response is not empty
        if not response_text or response_text.strip() == "":
            raise ValueError("Perplexity API returned an empty response")
        
        return response_text
    except Exception as e:
        print(f"Error calling Perplexity API: {e}")
        raise

def _extract_json(text: str) -> dict:
    """Robustly extract JSON from response text (handles markdown code blocks, etc.)"""
    text = text.strip()
    
    # Try to parse as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON from markdown code blocks (```json ... ```)
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # Try to extract raw JSON object/array from text
    # Find first { or [ and last } or ]
    for start_char in ['{', '[']:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        for end_char in ['}', ']']:
            end_idx = text.rfind(end_char)
            if end_idx > start_idx:
                json_str = text[start_idx:end_idx+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
    
    # If all else fails, raise an error
    raise ValueError(f"Could not extract JSON from response: {text[:200]}")

# --- PUBLIC AI FUNCTIONS ---

def get_corrected_job_title(job_title: str):
    """Uses Perplexity Sonar to correct spelling and standardize the user's input."""
    print(f"AI is correcting the job title: '{job_title}'")
    try:
        prompt = (
            f"Correct any spelling mistakes in the following job title and provide the standard, "
            f"professional name for it. Respond with ONLY the corrected job title. "
            f"Input: '{job_title}'"
        )
        response_text = call_llm(prompt)
        corrected_title = response_text.strip().replace('**', '')
        print(f"AI suggested corrected title: '{corrected_title}'")
        return corrected_title
    except Exception as e:
        print(f"Error during Perplexity title correction: {e}")
        return job_title

def get_loading_facts(job_title: str):
    """Generates interesting facts for the loading screen using Perplexity Sonar."""
    print(f" > Generating loading screen facts for '{job_title}'...")
    try:
        prompt = (
            f"For the career path of a '{job_title}', provide a JSON object with a 'facts' key, "
            f"containing an array of 4 short, interesting, one-sentence facts about this career."
        )
        response_text = call_llm(prompt, json_mode=True)
        return _extract_json(response_text)
    except Exception as e:
        print(f" - AI Error during loading facts generation: {e}")
        # Return a default object to prevent the app from crashing.
        return {
            "facts": [
                "The journey to a new career is a marathon, not a sprint.",
                "Continuous learning is key to success in any field.",
                "Networking can open doors to unexpected opportunities."
            ]
        }

# --- "ASSEMBLY LINE" HELPER FUNCTIONS ---

def _get_roadmap_step_titles(job_title: str):
    """Station 1: The Brainstormer. Gets only the titles of the roadmap steps using Perplexity Sonar."""
    prompt = (
        f"You are a career planner. What are the main sequential steps to become a '{job_title}'? "
        f"Respond with only a JSON object: {{\"steps\": [\"Step 1 Title\", \"Step 2 Title\", ...]}}."
    )
    response_text = call_llm(prompt, json_mode=True)
    content = _extract_json(response_text)
    return content.get("steps", [])

def _get_details_for_step(step_title: str):
    """Station 2: The Elaborator. Gets the description and skills for a single step title using Perplexity Sonar."""
    prompt = (
        f"For the topic '{step_title}', what is a good one-sentence description and what are the 3-5 most important skills to learn? "
        f"Respond with only a JSON object with 'description' and 'skills' keys (an array of strings)."
    )
    response_text = call_llm(prompt, json_mode=True)
    return _extract_json(response_text)

def _find_courses_for_step_with_focused_search(step_title: str):
    """Station 3: The Focused Researcher & Selector. Uses RAG to find reliable course links via Perplexity Sonar."""
    try:
        search_sites_filter = "site:udemy.com/course/ OR site:coursera.org/learn/ OR site:edx.org/course/ OR site:youtube.com/playlist OR site:freecodecamp.org/learn/"
        search_query = f"best '{step_title}' course {search_sites_filter}"
        
        context_results = tavily_client.search(query=search_query, max_results=7)
        search_context = "\n".join(
            [f"URL: {res['url']}\nTitle: {res['title']}\nContent: {res['content']}" 
             for res in context_results["results"]]
        )
        
        prompt = (
            f"You are an expert course selector. Based ONLY on the provided context, select the best free and paid course for '{step_title}'. "
            f"Context:\n---{search_context}\n---\n"
            f"Your response must be a JSON object with 'free_course' and 'paid_course' keys. "
            f"Each object must have a 'name', a direct 'url', and a 'reason' (for the paid course). If no course is found, return null."
        )
        
        response_text = call_llm(prompt, json_mode=True)
        return _extract_json(response_text)
    except Exception as e:
        print(f" - AI Error finding courses for '{step_title}': {e}")
        return {
            "free_course": {"name": "Not Found", "url": "#"},
            "paid_course": {"name": "Not Found", "url": "#"}
        }

def _build_mermaid_graph(steps: list):
    """Final Assembly: The Builder. Programmatically creates a valid Mermaid graph string."""
    graph_str = "graph TD\n"
    for i, step in enumerate(steps):
        clean_title = re.sub(r'[^a-zA-Z0-9\s-]', '', step['title'])
        graph_str += f" step{i}[{clean_title}]\n"
        if i > 0:
            graph_str += f" step{i-1} --> step{i}\n"
    return graph_str

def get_ai_roadmap(job_title: str, task_id: str, task_statuses: dict):
    """The main orchestrator for the 'AI Assembly Line' strategy using Perplexity Sonar, now with status updates."""
    print(f"Generating new roadmap from AI for: '{job_title}' using multi-step process")
    try:
        # --- Station 1: The Brainstormer ---
        task_statuses[task_id] = {
            "status": "running",
            "message": "Brainstorming core roadmap steps...",
            "progress": 10
        }
        step_titles = _get_roadmap_step_titles(job_title)
        
        if not step_titles:
            raise ValueError("AI Brainstormer failed to generate step titles.")
        
        full_roadmap_steps = []
        total_steps = len(step_titles)
        
        # --- Loop for Stations 2 & 3 ---
        for i, title in enumerate(step_titles):
            current_progress = 10 + int(80 * (i / total_steps))
            
            # --- Station 2: The Elaborator ---
            task_statuses[task_id] = {
                "status": "running",
                "message": f"[{i+1}/{total_steps}] Defining skills for '{title}'...",
                "progress": current_progress
            }
            details = _get_details_for_step(title)
            
            # --- Station 3: The Researcher ---
            task_statuses[task_id] = {
                "status": "running",
                "message": f"[{i+1}/{total_steps}] Searching for the best courses for '{title}'...",
                "progress": current_progress + int(80 / total_steps / 2)
            }
            courses = _find_courses_for_step_with_focused_search(title)
            
            # Assemble the complete object for this step.
            step_obj = {
                "title": title,
                "description": details.get("description", ""),
                "skills": details.get("skills", []),
                "free_course": courses.get("free_course"),
                "paid_course": courses.get("paid_course")
            }
            full_roadmap_steps.append(step_obj)
        
        # --- Final Assembly ---
        task_statuses[task_id] = {
            "status": "running",
            "message": "Assembling the final visual graph...",
            "progress": 95
        }
        mermaid_graph = _build_mermaid_graph(full_roadmap_steps)
        
        final_roadmap = {
            "roadmap": full_roadmap_steps,
            "mermaid_graph": mermaid_graph
        }
        
        # Return the final object as a JSON string.
        return json.dumps(final_roadmap)
    
    except Exception as e:
        # If any step fails, we re-raise the exception to be caught by the background task handler.
        print(f"Hybrid AI error during multi-step roadmap generation: {e}")
        raise e
