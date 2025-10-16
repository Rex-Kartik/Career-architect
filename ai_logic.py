# Import the os module, which provides a way of using operating system dependent functionality.
import os
# Import the json module, which is used for working with JSON data.
import json
# Import the 're' module for using regular expressions to clean up text.
import re
# Import the libraries for our Hybrid AI Engine.
import google.generativeai as genai
from tavily import TavilyClient
# Import a utility to load environment variables from a .env file.
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURE THE AI CLIENTS AND ADD VALIDATION ---
# This retrieves the API keys from the environment variables.
gemini_api_key = os.environ.get("GEMINI_API_KEY")
tavily_api_key = os.environ.get("TAVILY_API_KEY")

# This is a crucial validation step to ensure the application doesn't start without its required keys.
if not gemini_api_key or not tavily_api_key:
    raise ValueError("GEMINI_API_KEY or TAVILY_API_KEY not found. Please check your .env file.")

# This configures the Google AI library with your secret API key.
genai.configure(api_key=gemini_api_key)
# This creates the client object for the Tavily Search API.
tavily_client = TavilyClient(api_key=tavily_api_key)

# --- PUBLIC AI FUNCTIONS ---

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
        
        # Extract and clean the corrected title from the response.
        corrected_title = response.text.strip().replace('"', '')
        print(f"AI suggested corrected title: '{corrected_title}'")
        return corrected_title
    except Exception as e:
        print(f"Error during Gemini title correction: {e}")
        return job_title

def get_ai_roadmap(job_title: str):
    """
    Generates a new career roadmap using a single, fast RAG call with Gemini Pro and Tavily.
    """
    print(f"Generating new roadmap from AI for: '{job_title}' using Tavily and Gemini 2.5 Pro")
    try:
        # --- 1. RETRIEVAL PHASE (The Researcher) ---
        # We perform one broad search to get the latest context for the entire career path.
        search_query = f"career path and best free and paid online courses with direct links for a {job_title} in 2025"
        print(f"  > Performing web search with Tavily: '{search_query}'")
        context = tavily_client.search(query=search_query, max_results=10) # Get more context for better results
        # We format the search results into a clean string to be used as context for our reasoning AI.
        search_context = "\n".join([f"URL: {res['url']}\nTitle: {res['title']}\nContent: {res['content']}" for res in context["results"]])

        # --- 2. GENERATION PHASE (The Architect) ---
        # This is our main prompt engineering, instructing the AI on its role and desired output format.
        prompt = f"""
        You are an expert career advisor. Based ONLY on the provided web search context, create a comprehensive, step-by-step career roadmap.
        Here is the real-time web search context for '{job_title}':
        ---
        {search_context}
        ---
        Based on the context above, create a complete career roadmap.
        Your response must be a single, valid JSON object with "roadmap" and "mermaid_graph" keys.
        Each step in the "roadmap" array must have "title", "description", "skills", "free_course", and "paid_course" objects.
        - Each course object must have a "name" and a direct, valid "url" extracted from the context.
        - The "paid_course" object must also have a "reason" key explaining its value, based on the context.
        - The "mermaid_graph" string MUST be valid Mermaid.js syntax. Node IDs MUST be 'step0', 'step1', etc., and descriptions MUST NOT contain special characters like ':', '(', ')'.
        """
        
        print("  > Sending context to Gemini 2.5 Pro for generation...")
        # We use the powerful 'gemini-2.5-pro' for this main creative task.
        model = genai.GenerativeModel('gemini-2.5-pro')
        # We send the prompt and tell the model to guarantee a JSON response.
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        
        # We clean the response as a safeguard to remove markdown backticks.
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        # Return the final JSON string.
        return cleaned_text
        
    except Exception as e:
        print(f"Hybrid AI error during roadmap generation: {e}")
        return None

