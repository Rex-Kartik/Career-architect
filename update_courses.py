# Import the os module to access environment variables.
import os
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv
# Import the client classes from the Supabase library for database interaction.
from supabase import create_client, Client
# Import our new, separated AI helper functions.
from ai_logic import _get_course_ideas_for_step, _get_refined_course_details

def run_course_update():
    """The main function that runs the entire database update process using the two-stage RAG system."""
    
    print("\n--- [CRON JOB] Starting Monthly Course Update (Two-Stage Refinement) ---")
    
    try:
        # We initialize the Supabase client inside the function, using the environment variables.
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase credentials not found in environment.")
        supabase: Client = create_client(supabase_url, supabase_key)
        
        # Fetch all existing roadmaps from the database.
        response = supabase.table('roadmaps').select('id, job_title, roadmap_data').execute()
        
        if not response.data:
            print("[CRON JOB] No roadmaps found. Exiting.")
            return "No roadmaps found."

        print(f"[CRON JOB] Found {len(response.data)} roadmaps to check.")
        total_updates = 0

        # Loop through each roadmap record from the database.
        for record in response.data:
            needs_update = False
            roadmap_data = record['roadmap_data']
            job_title = record['job_title']
            print(f"  - Checking '{job_title.title()}'...")

            if 'roadmap' in roadmap_data and isinstance(roadmap_data['roadmap'], list):
                # Loop through each step within the current roadmap.
                for step in roadmap_data['roadmap']:
                    # We now call the separated AI functions imported from ai_logic.py.
                    course_ideas = _get_course_ideas_for_step(step.get('title', ''))
                    
                    if course_ideas:
                        # We then run the refinement pass for both the free and paid ideas.
                        refined_free_course = _get_refined_course_details(course_ideas.get('free_course'))
                        refined_paid_course = _get_refined_course_details(course_ideas.get('paid_course'))
                        
                        # We compare the refined URLs to see if an update is needed.
                        if refined_free_course and refined_free_course.get('url') and refined_free_course.get('url') != step.get('free_course', {}).get('url'):
                            step['free_course'] = refined_free_course
                            needs_update = True
                            print(f"    * Refreshed FREE course to: {refined_free_course.get('name')}")
                        
                        if refined_paid_course and refined_paid_course.get('url') and refined_paid_course.get('url') != step.get('paid_course', {}).get('url'):
                            step['paid_course'] = refined_paid_course
                            needs_update = True
                            print(f"    * Refreshed PAID course to: {refined_paid_course.get('name')}")

            # If any courses in this roadmap were updated, we save the entire modified object back to the database.
            if needs_update:
                total_updates += 1
                print(f"  -> Saving updates for '{job_title}'...")
                supabase.table('roadmaps').update({'roadmap_data': roadmap_data}).eq('id', record['id']).execute()
        
        summary = f"Update complete. Checked {len(response.data)} roadmaps and refreshed {total_updates} of them."
        print(f"--- {summary} ---")
        return summary

    except Exception as e:
        error_message = f"An error occurred during the update process: {e}"
        print(f"--- ERROR: {error_message} ---")
        return error_message

# This is the entry point that allows the script to be run directly from the command line.
if __name__ == '__main__':
    # We must load the environment variables from the .env file when running the script manually.
    load_dotenv()
    # We then call our main function to start the update process.
    run_course_update()

