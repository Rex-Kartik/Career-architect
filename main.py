# Import the os module, which provides a way of using operating system dependent functionality.
import os
# Import the json module, which is used for working with JSON data.
import json
# From the FastAPI library, we import the necessary components.
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
# Pydantic is used to define data shapes and validate incoming request data.
from pydantic import BaseModel
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv
# Import the client classes from the Supabase library for database interaction.
from supabase import create_client, Client
# Import the main logic function from our update script for the cron job.
from update_courses import run_course_update
# Import our separated module that now contains all AI-related logic.
import ai_logic

# This command finds the .env file and loads its key-value pairs as environment variables.
load_dotenv() 

# This creates our new web server application, an instance of the FastAPI class.
app = FastAPI()

# This line "mounts" the 'static' directory, allowing FastAPI to serve files like cuelinks.js.
app.mount("/static", StaticFiles(directory="static"), name="static")

# This tells FastAPI that our HTML files (templates) are located in a folder named 'templates'.
templates = Jinja2Templates(directory="templates")

# --- CONFIGURE DATABASE CLIENT ---
# We retrieve the Supabase credentials from the environment variables.
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
# We validate that the keys exist to prevent the app from starting in a broken state.
if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL or SUPABASE_KEY not found. Please check your .env file.")
# This creates a global Supabase client instance with admin privileges (using the secret key).
# This client is used for server-side tasks like reading from and writing to the public roadmap cache.
supabase_master_client: Client = create_client(supabase_url, supabase_key)

# --- PYDANTIC MODELS (DATA VALIDATION) ---
# This defines the expected structure for a request to create a roadmap. FastAPI will automatically validate this.
class RoadmapRequest(BaseModel):
    job_title: str

# --- DATABASE AND CACHING FUNCTIONS ---

def check_db_for_roadmap(job_title: str):
    """Checks the Supabase database for a publicly cached roadmap."""
    print(f"Checking database for roadmap: '{job_title}'")
    try:
        # We use the master client for this public, read-only operation.
        response = supabase_master_client.table('roadmaps').select('roadmap_data').eq('job_title', job_title.lower()).execute()
        if response.data:
            print("Roadmap found in cache.")
            return response.data[0]['roadmap_data']
    except Exception as e:
        print(f"Database check error: {e}")
    print("No roadmap found in cache.")
    return None

def save_roadmap_to_db(job_title: str, roadmap_data: dict):
    """Saves a newly generated roadmap to our Supabase database for future caching."""
    print(f"Saving roadmap for '{job_title}' to database.")
    try:
        # We use the master client for this server-side write operation.
        supabase_master_client.table('roadmaps').insert({'job_title': job_title.lower(), 'roadmap_data': roadmap_data}).execute()
        print("Save successful.")
    except Exception as e:
        print(f"Database save error: {e}")

def get_db_suggestions(query: str):
    """Searches the database for existing job titles to provide search suggestions."""
    try:
        # We use the master client for this public, read-only operation.
        response = supabase_master_client.table('roadmaps').select('job_title').ilike('job_title', f'%{query}%').limit(10).execute()
        if response.data:
            return [item['job_title'].title() for item in response.data]
    except Exception as e:
        print(f"Suggestion search error: {e}")
    return []

# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main index.html file and injects the necessary public environment variables."""
    # We pass the public keys as context variables to the Jinja2 template.
    return templates.TemplateResponse("index.html", {
        "request": request,
        "supabase_url": os.environ.get("SUPABASE_URL"),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY")
    })

@app.get("/api/search-suggestions")
async def search_suggestions(q: str = ""):
    """Provides real-time search suggestions as the user types."""
    if not q or len(q) < 2:
        return []
    return get_db_suggestions(q)

@app.post("/api/create-roadmap")
async def create_roadmap(request: RoadmapRequest):
    """Orchestrates the roadmap generation by calling the ai_logic module."""
    try:
        user_job_title = request.job_title
        if not user_job_title:
            raise HTTPException(status_code=400, detail="Job title is required.")
        
        # We call the function from our separate ai_logic module to correct the title.
        corrected_title = ai_logic.get_corrected_job_title(user_job_title)
        
        # We check the public cache for an existing roadmap.
        cached_roadmap = check_db_for_roadmap(corrected_title)
        if cached_roadmap:
            # If a cached version exists, we return it immediately.
            return {'roadmap_data': cached_roadmap, 'corrected_title': corrected_title}

        # If not cached, we call the main orchestrator function from our ai_logic module.
        ai_response_str = ai_logic.get_ai_roadmap(corrected_title)
        if not ai_response_str:
            raise HTTPException(status_code=500, detail="Failed to generate roadmap from AI.")

        try:
            # We parse the JSON string returned by the AI logic module.
            roadmap_json = json.loads(ai_response_str)
        except json.JSONDecodeError:
            print(f"Error: AI did not return valid JSON. Response was:\n{ai_response_str}")
            raise HTTPException(status_code=500, detail="The AI returned an invalid format.")

        # We save the newly generated roadmap to the database for future use.
        save_roadmap_to_db(corrected_title, roadmap_json)
        # We return the new roadmap to the user.
        return {'roadmap_data': roadmap_json, 'corrected_title': corrected_title}

    except Exception as e:
        print(f"An unexpected error occurred in /api/create-roadmap: {e}")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

@app.get("/api/update-courses")
async def trigger_course_update(request: Request):
    """The secret endpoint for the Vercel cron job."""
    auth_header = request.headers.get('Authorization')
    cron_secret = os.environ.get('CRON_SECRET')

    if not cron_secret or auth_header != f'Bearer {cron_secret}':
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = run_course_update()
    return {'message': 'Course update process finished.', 'summary': result}

