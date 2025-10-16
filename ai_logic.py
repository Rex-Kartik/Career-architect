# Import the os module, which provides a way of using operating system dependent functionality.
import os
# Import the json module, which is used for working with JSON data.
import json
# Import the 're' module for using regular expressions.
import re
# Import the libraries for our Hybrid AI Engine.
import google.generativeai as genai
from tavily import TavilyClient

# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# --- CONFIGURE THE AI CLIENTS AND ADD VALIDATION ---
# This retrieves the API keys from the environment.
tavily_api_key = os.environ.get("TAVILY_API_KEY")
gemini_api_key = os.environ.get("GEMINI_API_KEY")


# This is a crucial validation step to ensure keys are present.
if not gemini_api_key:
    raise ValueError("GEMINI_API_KEY not found. Please check your .env file.")
if not tavily_api_key:
    raise ValueError("TAVILY_API_KEY not found. Please check your .env file.")

# This configures the Google AI library with your secret API key.
genai.configure(api_key=gemini_api_key)
# This creates the client object for the Tavily Search API.
tavily_client = TavilyClient(api_key=tavily_api_key)

# --- "ASSEMBLY LINE" HELPER FUNCTIONS ---

def get_corrected_job_title(job_title: str):
    """Uses the FASTEST AI (Gemini Flash-Lite) to correct spelling and standardize the user's input."""
    print(f"AI is correcting the job title: '{job_title}'")
    try:
        # We create a simple, direct prompt for the AI.
        prompt = (f"Correct any spelling mistakes in the following job title and provide the standard, "
                  f"professional name for it. Respond with ONLY the corrected job title. "
                  f"Input: '{job_title}'")
        
        # We use 'gemini-2.5-flash-lite' as our specialist for this simple, high-frequency task.
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        # Send the prompt to the AI.
        response = model.generate_content(prompt)
        
        # Extract the corrected title from the response.
        corrected_title = response.text.strip().replace('"', '')
        print(f"AI suggested corrected title: '{corrected_title}'")
        return corrected_title
    except Exception as e:
        print(f"Error during Gemini title correction: {e}")
        return job_title

def _get_course_ideas_for_step(step_title: str):
    """Performs the first pass: a broad search to identify the NAMES of the best courses."""
    print(f"  > Pass 1: Identifying course names for '{step_title}'")
    try:
        # This part of the RAG system uses Tavily for web search.
        search_query = f"best free and paid online courses for '{step_title}'"
        context = tavily_client.search(query=search_query, max_results=5)
        search_context = "\n".join([f"Title: {res['title']}\nContent: {res['content']}" for res in context["results"]])
        
        # The prompt for the reasoning model is a single string for Gemini.
        prompt = (f"You are an expert course researcher. From the provided search results, identify the names of the single best FREE course and the single best PAID course and their platforms. "
                  f"Based on this context:\n---{search_context}\n---\n"
                  f"Identify the best free and paid course for '{step_title}'. Your response must be a JSON object with 'free_course' and 'paid_course' keys. Each object must have a 'name' and a 'platform' (e.g., 'Coursera', 'Udemy').")
        
        # We use the fast 'gemini-2.5-flash' model for this intermediate reasoning task.
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except Exception as e:
        print(f"    - AI Error during Pass 1 for step '{step_title}': {e}")
        return None

def _get_refined_course_details(course_idea: dict):
    """Performs the second pass: a highly focused search to validate and get the direct URL for a specific course."""
    if not course_idea or not course_idea.get("name") or not course_idea.get("platform"):
        return None
    course_name = course_idea["name"]
    platform = course_idea["platform"].lower()
    print(f"  > Pass 2: Validating URL for '{course_name}' on {platform}")
    try:
        # This part uses Tavily for a focused search.
        search_query = f'"{course_name}" site:{platform}.com'
        context = tavily_client.search(query=search_query, max_results=3)
        search_context = "\n".join([f"URL: {res['url']}\nTitle: {res['title']}\nContent: {res['content']}" for res in context["results"]])

        # The prompt for the reasoning model is a single string for Gemini.
        prompt = (f"You are a data extractor. Find the direct URL and a reason for a course from the provided text. "
                  f"Search result for '{course_name}':\n---{search_context}\n---\n"
                  f"Based ONLY on this context, what is the direct URL for the course? Respond with a JSON object with a 'url' key and a 'reason' key (for the paid course).")

        # We use the fast 'gemini-2.5-flash' model for this extraction task.
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        extracted_details = json.loads(response.text)
        
        # We assemble the final, validated course object.
        return {
            "name": course_name,
            "platform": platform.title(),
            "url": extracted_details.get("url"),
            "reason": extracted_details.get("reason", "")
        }
    except Exception as e:
        print(f"    - AI Error during Pass 2 for course '{course_name}': {e}")
        return None

def _build_mermaid_graph(steps: list):
    """Programmatically creates a valid Mermaid graph string."""
    print("  > Final Assembly: Building visual graph...")
    graph_str = "graph TD\n"
    for i, step in enumerate(steps):
        clean_title = re.sub(r'[^a-zA-Z0-9\s-]', '', step['title'])
        graph_str += f"    step{i}[{clean_title}]\n"
        if i > 0:
            graph_str += f"    step{i-1} --> step{i}\n"
    return graph_str

def get_ai_roadmap(job_title: str):
    """The main orchestrator for the 'Two-Stage Refinement' strategy."""
    print(f"Generating new roadmap from AI for: '{job_title}' using two-stage refinement")
    try:
        # --- Pass 1: Generate the core roadmap structure (titles, descriptions, skills) ---
        print("  > Pass 1: Generating core roadmap structure...")
        prompt = (f"You are an expert career planner. Create a logical sequence of high-level steps for the user's career goal. "
                  f"Create a step-by-step career roadmap for a '{job_title}'. "
                  f"Your response must be a JSON object: {{\"roadmap\": [{{\"title\": \"...\", \"description\": \"...\", \"skills\": [...]}}]}}")
        
        # We use the powerful 'gemini-2.5-pro' for this main creative task.
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        
        roadmap_structure = json.loads(response.text).get("roadmap", [])
        if not roadmap_structure:
            raise ValueError("AI Planner failed to generate roadmap structure.")

        # --- Pass 2: Loop through each step to find and refine courses ---
        print("\n  > Pass 2: Finding and refining courses for each step...")
        for step in roadmap_structure:
            course_ideas = _get_course_ideas_for_step(step.get('title', ''))
            step['free_course'] = _get_refined_course_details(course_ideas.get('free_course'))
            step['paid_course'] = _get_refined_course_details(course_ideas.get('paid_course'))

        # --- Final Assembly ---
        mermaid_graph = _build_mermaid_graph(roadmap_structure)
        final_roadmap = {"roadmap": roadmap_structure, "mermaid_graph": mermaid_graph}
        return json.dumps(final_roadmap)
        
    except Exception as e:
        print(f"Hybrid AI error during two-stage roadmap generation: {e}")
        return None

def refine_roadmap_with_user_answers(initial_roadmap: dict, answers: dict):
    """Takes an initial roadmap and user answers, and returns a final, personalized roadmap."""
    print("  > Refining roadmap with user preferences...")
    try:
        # The prompt for the refinement pass.
        refinement_prompt = f"""
        Here is a generated career roadmap:
        ---
        {json.dumps(initial_roadmap, indent=2)}
        ---
        Here are the user's preferences:
        - Experience Level: {answers.get('experience')}
        - Learning Style: {answers.get('style')}
        - Weekly Time Commitment: {answers.get('time')}

        Please refine the roadmap based on these preferences. Adjust the descriptions and course recommendations.
        Your response must be the final, refined roadmap in the exact same JSON format as the input.
        """
        
        # We use the powerful Gemini 2.5 Pro for the refinement task.
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content(refinement_prompt, generation_config={"response_mime_type": "application/json"})
        
        # We parse and return the final JSON object.
        return json.loads(response.text)
    except Exception as e:
        print(f"An error occurred during roadmap refinement: {e}")
        return None

