# Import the os module to access environment variables.
import os
# Import the json module to work with JSON data.
import json
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv
# Import the client classes from the Supabase library for database interaction.
from supabase import create_client, Client
# Import our single, powerful AI roadmap generation function from the ai_logic module.
# This ensures our update script uses the exact same logic as our live application.
from ai_logic import get_ai_roadmap

def run_course_update():
    """
    The main function that runs the entire database update process.
    It now uses the consistent, single-call RAG system from ai_logic.py.
    """
    
    print("\n--- [CRON JOB] Starting Monthly Course Update (Single-Call RAG) ---")
    
    try:
        # We initialize the Supabase client inside the function, using the environment variables.
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase credentials not found in environment.")
        supabase: Client = create_client(supabase_url, supabase_key)
        
        # Fetch all existing roadmaps from the database to be updated.
        # We only need the 'id' and 'job_title' to perform the update.
        response = supabase.table('roadmaps').select('id, job_title').execute()
        
        if not response.data:
            print("[CRON JOB] No roadmaps found. Exiting.")
            return "No roadmaps found."

        print(f"[CRON JOB] Found {len(response.data)} roadmaps to re-evaluate and update.")
        
        # Loop through each roadmap record from the database.
        for record in response.data:
            job_title = record['job_title']
            print(f"  - Re-generating roadmap for '{job_title.title()}'...")
            
            # We call our main AI function to generate a completely new, up-to-date roadmap
            # based on the latest real-time web search results.
            ai_response_str = get_ai_roadmap(job_title)
            
            # If the AI successfully generated a new roadmap...
            if ai_response_str:
                try:
                    # ...we parse the new JSON data...
                    new_roadmap_data = json.loads(ai_response_str)
                    # ...and then update the existing record in the database with the fresh data,
                    # identifying the row by its unique 'id'.
                    supabase.table('roadmaps').update({'roadmap_data': new_roadmap_data}).eq('id', record['id']).execute()
                    print(f"    * Successfully updated roadmap for '{job_title.title()}'.")
                except Exception as e:
                    # If parsing or saving fails for this specific roadmap, we log it and continue to the next one.
                    print(f"    - FAILED to parse or save update for '{job_title.title()}': {e}")
            else:
                # If the AI fails to generate a roadmap, we log it and move on.
                print(f"    - FAILED to generate new roadmap for '{job_title.title()}'. Skipping.")

        summary = f"Update complete. Processed {len(response.data)} roadmaps."
        print(f"--- {summary} ---")
        return summary

    except Exception as e:
        error_message = f"An error occurred during the update process: {e}"
        print(f"--- ERROR: {error_message} ---")
        return error_message

# This is the entry point that allows the script to be run directly from the command line.
# For example, by running `python update_courses.py` in your terminal.
if __name__ == '__main__':
    # We must load the environment variables from the .env file when running the script manually.
    load_dotenv()
    # We then call our main function to start the update process.
    run_course_update()

