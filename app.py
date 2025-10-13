# --- IMPORT NECESSARY LIBRARIES ---
import os  # Used to access environment variables (our secret keys)
import json # Used to parse JSON data from the AI's response
from flask import Flask, render_template, request, jsonify # Core components for our Flask web server
import google.generativeai as genai # The official Google AI Python library
from dotenv import load_dotenv # A utility to load environment variables from a .env file
from supabase import create_client, Client # The official Supabase library for database interaction

# --- SETUP AND INITIALIZATION ---

# This command finds and loads the variables from your .env file (e.g., your API keys)
load_dotenv() 
# This creates our web server application, an instance of the Flask class.
app = Flask(__name__) 

# This configures the Google AI library with your secret API key.
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# These lines retrieve your Supabase credentials from the environment.
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
# This creates the Supabase client object, which is our gateway to the database.
supabase: Client = create_client(supabase_url, supabase_key)

# --- HELPER FUNCTIONS (The core logic of our app) ---

def get_corrected_job_title(job_title: str):
    """Uses a focused AI call to correct spelling and standardize the user's input."""
    print(f"AI is correcting the job title: '{job_title}'")
    try:
        # We create a very specific prompt to ensure the AI's response is fast and accurate.
        prompt = (f"Correct any spelling mistakes in the following job title and provide the standard, "
                  f"professional name for it. Respond with ONLY the corrected job title and nothing else. "
                  f"For example, if the input is 'ful stak web dev', the output should be 'Full Stack Web Developer'. "
                  f"Input: '{job_title}'")
        
        # Initialize the Gemini model. 'gemini-2.5-flash' is fast and cost-effective for simple tasks like this.
        model = genai.GenerativeModel('gemini-2.5-flash')
        # Send the prompt to the AI.
        response = model.generate_content(prompt)
        
        # Clean up the AI's response to remove any extra characters or quotes.
        corrected_title = response.text.strip().replace('"', '')
        print(f"AI suggested corrected title: '{corrected_title}'")
        return corrected_title
    except Exception as e:
        # If the correction fails for any reason, we safely fall back to the user's original input.
        print(f"Error during AI title correction: {e}")
        return job_title

def check_db_for_roadmap(job_title: str):
    """Checks the Supabase database to see if we've already generated this roadmap."""
    print(f"Checking database for roadmap: '{job_title}'")
    try:
        # This builds a query: SELECT roadmap_data FROM roadmaps WHERE job_title = [our title]
        response = supabase.table('roadmaps').select('roadmap_data').eq('job_title', job_title.lower()).execute()
        
        # If the 'data' list in the response is not empty, it means we found a match.
        if response.data:
            print("Roadmap found in cache.")
            # We return the roadmap data from the first (and only) result.
            return response.data[0]['roadmap_data']
    except Exception as e:
        print(f"Database check error: {e}")
    
    print("No roadmap found in cache.")
    return None # Return None to signal that we need to generate a new roadmap.

def get_ai_roadmap(job_title: str):
    """Generates a new roadmap by calling the Gemini API with a detailed prompt."""
    print(f"Generating new roadmap from AI for: '{job_title}'")
    # This is our main "prompt engineering". We give the AI very strict instructions.
    prompt = f"""
    Create a comprehensive, step-by-step career roadmap for becoming a "{job_title}".
    Your response MUST be a single, valid JSON object. Do not include any text or formatting before or after the JSON.
    The JSON object must have two top-level keys: "roadmap" and "mermaid_graph".
    - "roadmap" should be an array of objects, where each object represents a step in the career path.
    - Each step object must contain the following keys: "title", "description", "skills" (an array of strings), and "free_course" (an object with "name" and "url").
    - "mermaid_graph" should be a string containing the Mermaid.js syntax for a flowchart (graph TD).
    - The Mermaid graph nodes MUST use predictable IDs like "step0", "step1", "step2", etc., corresponding to their order.
    - The node descriptions MUST NOT contain special characters like parentheses or colons to avoid syntax errors.

    Example of the required JSON structure:
    {{
      "roadmap": [
        {{
          "title": "Step 1 Foundational Skills",
          "description": "Start with the absolute basics of programming and computer science.",
          "skills": ["Python Basics", "Data Structures", "Algorithms"],
          "free_course": {{
            "name": "freeCodeCamp - Python for Everybody",
            "url": "https://www.freecodecamp.org/learn/scientific-computing-with-python/"
          }}
        }}
      ],
      "mermaid_graph": "graph TD\\nstep0[Step 1 Foundational Skills] --> step1[Step 2 Specialization]"
    }}
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        # We send the prompt and tell the model to guarantee a JSON response.
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return response.text
    except Exception as e:
        print(f"Gemini API error during roadmap generation: {e}")
        return None

def save_roadmap_to_db(job_title: str, roadmap_data: dict):
    """Saves a newly generated roadmap to our Supabase database."""
    print(f"Saving roadmap for '{job_title}' to database.")
    try:
        # This inserts a new row into the 'roadmaps' table.
        supabase.table('roadmaps').insert({
            'job_title': job_title.lower(), # Save in lowercase for consistent lookups.
            'roadmap_data': roadmap_data   # The complete JSON data for the roadmap.
        }).execute()
        print("Save successful.")
    except Exception as e:
        print(f"Database save error: {e}")

def get_db_suggestions(query: str):
    """Searches the database for job titles that match the user's query."""
    try:
        # 'ilike' performs a case-insensitive search. '%' is a wildcard.
        # This finds any title containing the query string.
        response = supabase.table('roadmaps').select('job_title').ilike('job_title', f'%{query}%').limit(10).execute()
        if response.data:
            # We transform the list of objects [{'job_title': 'x'}, ...] into a simple list ['x', ...]
            return [item['job_title'].title() for item in response.data]
    except Exception as e:
        print(f"Suggestion search error: {e}")
    return []


# --- FLASK ROUTES (The entry points for our web server) ---

# This decorator defines the root URL (e.g., "http://127.0.0.1:5001/")
@app.route('/')
def index():
    """Renders the main HTML page when the user visits the site."""
    return render_template('index.html') # Flask looks for this file in the 'templates' folder.

# This decorator defines the URL for our search suggestions API.
@app.route('/api/search-suggestions')
def search_suggestions():
    """Provides real-time search suggestions as the user types."""
    # Get the search query 'q' from the URL parameters (e.g., /api/search-suggestions?q=data)
    query = request.args.get('q', '')
    # Don't search if the query is too short.
    if not query or len(query) < 2:
        return jsonify([])
    suggestions = get_db_suggestions(query)
    # Return the suggestions as a JSON array.
    return jsonify(suggestions)

# This decorator defines the main API endpoint for creating roadmaps. It only accepts POST requests.
@app.route('/api/create-roadmap', methods=['POST'])
def create_roadmap():
    """The main endpoint that orchestrates the roadmap creation process."""
    data = request.get_json() # Get the JSON data sent from the frontend.
    user_job_title = data.get('job_title')
    if not user_job_title:
        return jsonify({'error': 'Job title is required.'}), 400
        
    # The main logic flow: Correct -> Check Cache -> Generate (if needed) -> Save -> Return
    corrected_title = get_corrected_job_title(user_job_title)
    cached_roadmap = check_db_for_roadmap(corrected_title)
    if cached_roadmap:
        return jsonify(cached_roadmap)

    ai_response_str = get_ai_roadmap(corrected_title)
    if not ai_response_str:
        return jsonify({'error': 'Failed to generate roadmap from AI.'}), 500

    try:
        roadmap_json = json.loads(ai_response_str)
    except json.JSONDecodeError:
        print("Error: AI did not return valid JSON.")
        return jsonify({'error': 'Failed to parse AI response.'}), 500

    save_roadmap_to_db(corrected_title, roadmap_json)
    return jsonify(roadmap_json)

# This standard Python construct ensures the server only runs when the script is executed directly.
if __name__ == '__main__':
    # Starts the Flask development server. debug=True enables auto-reloading and detailed error pages.
    app.run(debug=True, port=5001)

