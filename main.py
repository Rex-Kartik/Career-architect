# Import the os module, which provides a way of using operating system dependent functionality.
import os
# Import the json module, which is used for working with JSON data.
import json
# Import asyncio for managing locks and async operations.
import asyncio
# Import uuid to generate unique task IDs for the background process.
import uuid
import requests
import time
# From the FastAPI library, we import the necessary components, including BackgroundTasks.
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv
# Import the client classes from the Supabase library for database interaction.
from supabase import create_client, Client
# Import our separated module that now contains all AI-related logic.
import ai_logic

# This command finds the .env file and loads its key-value pairs as environment variables.
load_dotenv() 

# This creates our new web server application, an instance of the FastAPI class.
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- CONFIGURE DATABASE CLIENT ---
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL or SUPABASE_KEY not found. Please check your .env file.")
supabase_master_client: Client = create_client(supabase_url, supabase_key)


def verify_supabase_token(access_token: str):
    """Verify a Supabase access token by calling the Supabase Auth user endpoint.

    Returns the user JSON on success, or None on failure. This avoids needing the
    project's JWT secret on the server.
    """
    try:
        if not access_token:
            return None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "apikey": supabase_anon_key or "",
        }
        resp = requests.get(f"{supabase_url}/auth/v1/user", headers=headers, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        print(f"Token verification failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Error verifying Supabase token: {e}")
    return None


# --- Token verification cache ---
_token_verification_cache = {}
# seconds to cache a verified token
_TOKEN_CACHE_TTL = int(os.environ.get("TOKEN_CACHE_TTL", "300"))

def verify_supabase_token_cached(access_token: str):
    """Verify token but cache successful results for _TOKEN_CACHE_TTL seconds.

    Returns user JSON on success or None on failure.
    """
    if not access_token:
        return None
    now = time.time()
    cache_entry = _token_verification_cache.get(access_token)
    if cache_entry:
        user, expires_at = cache_entry
        if expires_at > now:
            return user
        # expired - delete
        del _token_verification_cache[access_token]

    user = verify_supabase_token(access_token)
    if user:
        _token_verification_cache[access_token] = (user, now + _TOKEN_CACHE_TTL)
    return user

# --- In-Memory Task Management ---
# This dictionary will store the status of our background tasks, accessible by their unique task_id.
task_statuses = {}

# --- PYDANTIC MODELS (DATA VALIDATION) ---
class RoadmapRequest(BaseModel):
    job_title: str

# --- DATABASE AND CACHING FUNCTIONS ---
def check_db_for_roadmap(job_title: str):
    """Checks the Supabase database for a publicly cached roadmap."""
    print(f"Checking database for roadmap: '{job_title}'")
    try:
        response = supabase_master_client.table('roadmaps').select('roadmap_data').eq('job_title', job_title.lower()).execute()
        if response.data:
            print("Roadmap found in cache.")
            return response.data[0]['roadmap_data']
    except Exception as e:
        print(f"Database check error: {e}")
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
    """Searches the database for existing job titles to provide search suggestions."""
    try:
        response = supabase_master_client.table('roadmaps').select('job_title').ilike('job_title', f'%{query}%').limit(10).execute()
        if response.data:
            return [item['job_title'].title() for item in response.data]
    except Exception as e:
        print(f"Suggestion search error: {e}")
    return []

# --- BACKGROUND TASK ---
def background_roadmap_generation(corrected_title: str, task_id: str):
    """This function runs in the background to generate and save the roadmap, providing status updates along the way."""
    try:
        # We pass the task_id and the statuses dictionary to the AI logic module so it can post live updates.
        ai_response_str = ai_logic.get_ai_roadmap(corrected_title, task_id, task_statuses)
        roadmap_json = json.loads(ai_response_str)
        save_roadmap_to_db(corrected_title, roadmap_json)
        # When finished, we update the status to 'complete' and store the final result.
        task_statuses[task_id] = {"status": "complete", "result": {'roadmap_data': roadmap_json, 'corrected_title': corrected_title}}
    except Exception as e:
        print(f"Background task failed: {e}")
        # If the task fails at any point, we update the status to 'error'.
        task_statuses[task_id] = {"status": "error", "message": "Failed to generate the roadmap. Please try again."}

# --- API ENDPOINTS ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main index.html file and injects environment variables."""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "supabase_url": os.environ.get("SUPABASE_URL"),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY")
    })

@app.get("/api/search-suggestions")
async def search_suggestions(q: str = ""):
    if not q or len(q) < 2: return []
    return get_db_suggestions(q)

@app.post("/api/create-roadmap")
async def create_roadmap(request: Request, payload: RoadmapRequest, background_tasks: BackgroundTasks):
    """This endpoint now starts a background task and immediately returns a task ID and loading content.

    Optional: If the frontend includes an Authorization header (Supabase access token), we log it here.
    Server-side verification of the token is not implemented in this patch — see README or comments for
    instructions on verifying Supabase JWTs on the server.
    """
    user_job_title = payload.job_title
    # Read Authorization header if present (frontend may send Supabase access token)
    auth_header = request.headers.get('authorization') or request.headers.get('Authorization')
    current_user = None
    if auth_header:
        try:
            token = auth_header.split(' ')[1]
            # Verify token with Supabase (using cache)
            user = verify_supabase_token_cached(token)
            if not user:
                raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")
            current_user = user
            print(f"Authenticated request from user: {user.get('email')}")
        except HTTPException:
            raise
        except Exception:
            print("Malformed Authorization header received.")
    if not user_job_title: raise HTTPException(status_code=400, detail="Job title is required.")
    
    corrected_title = ai_logic.get_corrected_job_title(user_job_title)
    
    cached_roadmap = check_db_for_roadmap(corrected_title)
    if cached_roadmap:
        return {'final_roadmap': cached_roadmap, 'corrected_title': corrected_title}

    # If not cached, get the loading screen content.
    loading_content = ai_logic.get_loading_facts(corrected_title)
    
    # Generate a unique ID for this new generation task.
    task_id = str(uuid.uuid4())
    task_statuses[task_id] = {"status": "pending", "message": "Initializing..."}
    
    # Add the long-running AI generation function to FastAPI's background tasks.
    background_tasks.add_task(background_roadmap_generation, corrected_title, task_id)
    
    # Immediately return the task ID and loading content to the user.
    return JSONResponse(content={"task_id": task_id, "corrected_title": corrected_title, "loading_content": loading_content}, status_code=202)

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """This new endpoint allows the frontend to poll for the status of a background task."""
    status = task_statuses.get(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # If the task is complete or has failed, we can return the result and clean up the status entry.
    if status.get("status") == "complete" or status.get("status") == "error":
        return task_statuses.pop(task_id)
        
    return status

