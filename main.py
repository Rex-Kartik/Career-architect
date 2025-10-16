# Import the os module, which provides a way of using operating system dependent functionality.
import os
# Import the json module, which is used for working with JSON data.
import json
# Import the 're' module for using regular expressions.
import re
# From the FastAPI library, we import the necessary components.
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
# Import StaticFiles to serve our static JavaScript file (cuelinks.js).
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv
# Import the client classes from the Supabase library for database interaction.
from supabase import create_client, Client
# Import the main logic function from our update script.
from update_courses import run_course_update
# Import our new, separated module for all AI-related logic.
import ai_logic

# This command finds the .env file and loads its key-value pairs as environment variables.
load_dotenv() 

# This creates our new web server application, an instance of the FastAPI class.
app = FastAPI()

# This line "mounts" the 'static' directory. It tells FastAPI that any request
# that starts with '/static' should be served from the folder named 'static' in our project.
app.mount("/static", StaticFiles(directory="static"), name="static")

# This tells FastAPI that our HTML files (templates) are located in a folder named 'templates'.
templates = Jinja2Templates(directory="templates")

# --- CONFIGURE DATABASE CLIENT ---
supabase_url = os.environ.get("SUPABASE_URL")
# The service_role key is used for admin-level operations on the backend.
supabase_key = os.environ.get("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL or SUPABASE_KEY not found. Please check your .env file.")
# This creates a global Supabase client instance with admin privileges.
supabase_master_client: Client = create_client(supabase_url, supabase_key)

# Pydantic models for request body validation.
class RoadmapRequest(BaseModel):
    job_title: str

class UserPreferences(BaseModel):
    experience: str
    style: str
    time: str

class RefineRequest(BaseModel):
    initial_roadmap: dict
    answers: UserPreferences
    corrected_title: str

# --- AUTHENTICATION HELPER (FASTAPI DEPENDENCY) ---
async def get_supabase_client(request: Request) -> Client:
    # It gets the Authorization header (containing the user's token) from the incoming request.
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # It creates a new, user-specific Supabase client using that token.
    # The 'anon' key is used here because this client acts on behalf of the user.
    return create_client(supabase_url, os.environ.get("SUPABASE_ANON_KEY"), headers={"Authorization": auth_header})

# --- DATABASE AND CACHING FUNCTIONS ---
def check_db_for_roadmap(job_title: str):
    """Checks the Supabase database for a cached roadmap."""
    print(f"Checking database for roadmap: '{job_title}'")
    try:
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
        supabase_master_client.table('roadmaps').insert({'job_title': job_title.lower(), 'roadmap_data': roadmap_data}).execute()
        print("Save successful.")
    except Exception as e:
        print(f"Database save error: {e}")

def get_db_suggestions(query: str):
    """Searches the database for existing job titles that match the user's search query."""
    try:
        response = supabase_master_client.table('roadmaps').select('job_title').ilike('job_title', f'%{query}%').limit(10).execute()
        if response.data:
            return [item['job_title'].title() for item in response.data]
    except Exception as e:
        print(f"Suggestion search error: {e}")
    return []

# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    This endpoint serves the main index.html file and injects the necessary environment variables.
    """
    # We pass the public keys as context variables to the template.
    return templates.TemplateResponse("index.html", {
        "request": request,
        "supabase_url": os.environ.get("SUPABASE_URL"),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY")
    })

# The rest of the endpoints remain exactly the same.
@app.get("/api/search-suggestions")
async def search_suggestions(q: str = ""):
    if not q or len(q) < 2: return []
    return get_db_suggestions(q)

@app.post("/api/create-roadmap")
async def create_roadmap(request: RoadmapRequest):
    try:
        user_job_title = request.job_title
        if not user_job_title: raise HTTPException(status_code=400, detail="Job title is required.")
        corrected_title = ai_logic.get_corrected_job_title(user_job_title)
        cached_roadmap = check_db_for_roadmap(corrected_title)
        if cached_roadmap: return {'final_roadmap': cached_roadmap, 'corrected_title': corrected_title}
        ai_response_str = ai_logic.get_ai_roadmap(corrected_title)
        if not ai_response_str: raise HTTPException(status_code=500, detail="Failed to generate roadmap from AI.")
        try:
            roadmap_json = json.loads(ai_response_str)
        except json.JSONDecodeError:
            print(f"Error: AI did not return valid JSON. Response was:\n{ai_response_str}")
            raise HTTPException(status_code=500, detail="The AI returned an invalid format. Please try again.")
        return {'initial_roadmap': roadmap_json, 'corrected_title': corrected_title}
    except Exception as e:
        print(f"An unexpected error occurred in /api/create-roadmap: {e}")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

@app.post("/api/refine-roadmap")
async def refine_roadmap(request: RefineRequest):
    try:
        final_roadmap = ai_logic.refine_roadmap_with_user_answers(
            initial_roadmap=request.initial_roadmap,
            answers=request.answers.dict()
        )
        if not final_roadmap: raise HTTPException(status_code=500, detail="Failed to refine roadmap.")
        save_roadmap_to_db(request.corrected_title, final_roadmap)
        return {'final_roadmap': final_roadmap}
    except Exception as e:
        print(f"An error occurred during roadmap refinement: {e}")
        raise HTTPException(status_code=500, detail="An error occurred during the refinement process.")

@app.post("/api/save-preferences")
async def save_preferences(preferences: UserPreferences, supabase: Client = Depends(get_supabase_client)):
    try:
        user_id = (await supabase.auth.get_user()).user.id
        await supabase.table('user_preferences').upsert({
            'user_id': user_id,
            'experience': preferences.experience,
            'style': preferences.style,
            'time': preferences.time
        }).execute()
        return {"message": "Preferences saved successfully"}
    except Exception as e:
        print(f"Error saving preferences: {e}")
        raise HTTPException(status_code=500, detail="Could not save preferences.")

@app.get("/api/get-preferences")
async def get_preferences(supabase: Client = Depends(get_supabase_client)):
    try:
        user_id = (await supabase.auth.get_user()).user.id
        response = await supabase.table('user_preferences').select('*').eq('user_id', user_id).limit(1).single().execute()
        if response.data: return response.data
        else: return {}
    except Exception as e:
        print(f"Error getting preferences: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve preferences.")

@app.get("/api/update-courses")
async def trigger_course_update(request: Request):
    auth_header = request.headers.get('Authorization')
    cron_secret = os.environ.get('CRON_SECRET')
    if not cron_secret or auth_header != f'Bearer {cron_secret}':
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = run_course_update()
    return {'message': 'Course update process finished.', 'summary': result}

