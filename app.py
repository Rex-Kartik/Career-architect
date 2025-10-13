# Import the os module to access environment variables like API keys.
import os
# Import the json module to work with JSON data from the AI's response.
import json
# Import the necessary components from the Flask library to create our web server.
from flask import Flask, render_template, request, jsonify
# Import the official Google AI Python library.
import google.generativeai as genai
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv
# Import the official Supabase library for database interaction.
from supabase import create_client, Client

# This command finds and loads the variables from your .env file.
load_dotenv() 

# --- VERCEL CHANGE: The Flask app is now initialized at the top level. ---
# This allows Vercel's build system to import the 'app' object from this file.
app = Flask(__name__) 

# This configures the Google AI library with your secret API key from the environment variables.
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# These lines retrieve your Supabase credentials from the environment.
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
# This creates the Supabase client object, which is our gateway to the database.
supabase: Client = create_client(supabase_url, supabase_key)

def get_corrected_job_title(job_title: str):
    """Uses AI to correct spelling and standardize the user's input."""
    print(f"AI is correcting the job title: '{job_title}'")
    try:
        prompt = (f"Correct any spelling mistakes in the following job title and provide the standard, "
                  f"professional name for it. Respond with ONLY the corrected job title and nothing else. "
                  f"For example, if the input is 'ful stak web dev', the output should be 'Full Stack Web Developer'. "
                  f"Input: '{job_title}'")
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        
        corrected_title = response.text.strip().replace('"', '')
        print(f"AI suggested corrected title: '{corrected_title}'")
        return corrected_title
    except Exception as e:
        print(f"Error during AI title correction: {e}")
        return job_title

def check_db_for_roadmap(job_title: str):
    """Checks the Supabase database for an existing roadmap."""
    print(f"Checking database for roadmap: '{job_title}'")
    try:
        response = supabase.table('roadmaps').select('roadmap_data').eq('job_title', job_title.lower()).execute()
        
        if response.data:
            print("Roadmap found in cache.")
            return response.data[0]['roadmap_data']
    except Exception as e:
        print(f"Database check error: {e}")
    
    print("No roadmap found in cache.")
    return None

def get_ai_roadmap(job_title: str):
    """Generates a new roadmap by calling the Gemini API with a detailed prompt."""
    print(f"Generating new roadmap from AI for: '{job_title}'")
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
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
            
        return cleaned_text
    except Exception as e:
        print(f"Gemini API error during roadmap generation: {e}")
        return None

def save_roadmap_to_db(job_title: str, roadmap_data: dict):
    """Saves a newly generated roadmap to our Supabase database."""
    print(f"Saving roadmap for '{job_title}' to database.")
    try:
        supabase.table('roadmaps').insert({
            'job_title': job_title.lower(),
            'roadmap_data': roadmap_data
        }).execute()
        print("Save successful.")
    except Exception as e:
        print(f"Database save error: {e}")

def get_db_suggestions(query: str):
    """Searches the database for job titles that match the user's query."""
    try:
        response = supabase.table('roadmaps').select('job_title').ilike('job_title', f'%{query}%').limit(10).execute()
        if response.data:
            capitalized_suggestions = [item['job_title'].title() for item in response.data]
            return capitalized_suggestions
    except Exception as e:
        print(f"Suggestion search error: {e}")
    return []


@app.route('/')
def index():
    """Renders the main HTML page when the user visits the site."""
    return render_template('index.html')

@app.route('/api/search-suggestions')
def search_suggestions():
    """Provides real-time search suggestions as the user types."""
    query = request.args.get('q', '')
    if not query or len(query) < 2:
        return jsonify([])
    suggestions = get_db_suggestions(query)
    return jsonify(suggestions)

@app.route('/api/create-roadmap', methods=['POST'])
def create_roadmap():
    """The main endpoint that orchestrates the entire roadmap creation process."""
    try:
        data = request.get_json()
        user_job_title = data.get('job_title')

        if not user_job_title:
            return jsonify({'error': 'Job title is required.'}), 400
        
        corrected_title = get_corrected_job_title(user_job_title)
        
        cached_roadmap = check_db_for_roadmap(corrected_title)

        if cached_roadmap:
            return jsonify({'roadmap_data': cached_roadmap, 'corrected_title': corrected_title})

        ai_response_str = get_ai_roadmap(corrected_title)

        if not ai_response_str:
            return jsonify({'error': 'Failed to generate roadmap from AI. The model may be unavailable or overloaded.'}), 500

        try:
            roadmap_json = json.loads(ai_response_str)
        except json.JSONDecodeError:
            print(f"Error: AI did not return valid JSON. Response was:\n{ai_response_str}")
            return jsonify({'error': 'The AI returned an invalid format. Please try again.'}), 500

        save_roadmap_to_db(corrected_title, roadmap_json)
        return jsonify({'roadmap_data': roadmap_json, 'corrected_title': corrected_title})

    except Exception as e:
        print(f"An unexpected error occurred in /api/create-roadmap: {e}")
        return jsonify({'error': 'An unexpected server error occurred. Please check the server logs.'}), 500

# The if __name__ == '__main__': block is no longer needed for Vercel,
# but it's good practice to keep it for local development.
# Vercel will ignore this block.
if __name__ == '__main__':
    app.run(debug=True, port=5001)

