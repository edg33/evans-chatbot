import requests
from flask import Flask, request, jsonify
from llmproxy import generate
import os

app = Flask(__name__)

def google_search(query, site_filter="youtube.com"):
    """Queries Google Search API and returns the first YouTube result link."""
    search_url = "https://www.googleapis.com/customsearch/v1"
    
    params = {
        "key": os.environ.get("GOOGLE_API_KEY"),
        "cx": os.environ.get("GOOGLE_CSE_ID"),
        "q": query,
        "num": 1
    }
    
    if site_filter:
        params["q"] += f" site:{site_filter}"
    
    response = requests.get(search_url, params=params)
    
    if response.status_code == 200:
        search_results = response.json().get("items", [])
        if search_results:
            return search_results[0]["link"]
    print(f"Error: {response.status_code}, {response.text}")
    return None

@app.route('/', methods=['POST'])
def handle_request():
    data = request.get_json()
    user = data.get("user_name", "Unknown")
    message = data.get("text", "")

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message from {user}: {message}")

    # Socratic TA Agent — gently guides
    response = generate(
        model='4o-mini',
        system=(
            "You are a helpful teaching assistant in a university class. "
            "Your goal is to guide students to discover answers on their own rather than providing direct answers. "
            "Ask follow-up questions that help them think critically. "
            "If the student asks about an algorithm or programming concept, check if they need further resources, "
            "such as a YouTube video tutorial. Be encouraging and supportive, and never dismissive. "
            "If the question is unrelated to an algorithms or data structures class, gently remind them of your purpose."
        ),
        query=f"{message}",
        temperature=0.5,
        lastk=5,
        session_id=user
    )

    ta_reply = response["response"]

    # Check if this is an algorithm-related query
    keyword_check = generate(
        model="4o-mini",
        system="Identify whether this question is about a specific computer science algorithm or concept. Respond with 'yes' or 'no'.",
        query=message,
        temperature=0.0,
        lastk=0,
        session_id=user + "_alg_check"
    )

    is_algorithm = keyword_check["response"].strip().lower() == "yes"

    final_text = ta_reply

    if is_algorithm:
        video_link = google_search(message, site_filter="youtube.com")
        if video_link:
            final_text += f"\n\nYou might find this helpful: {video_link}"

    # Add response buttons
    response_with_buttons = {
        "text": final_text,
        "attachments": [
            {
                "text": "Need more help?",
                "actions": [
                    {
                        "type": "button",
                        "text": "Try a different explanation",
                        "msg": "explain again",
                        "msg_in_chat_window": True,
                        "msg_processing_type": "sendMessage"
                    },
                    {
                        "type": "button",
                        "text": "Show me examples",
                        "msg": "examples",
                        "msg_in_chat_window": True,
                        "msg_processing_type": "sendMessage"
                    },
                    {
                        "type": "button",
                        "text": "Restart",
                        "msg": "restart",
                        "msg_in_chat_window": True,
                        "msg_processing_type": "sendMessage"
                    }
                ]
            }
        ]
    }

    return jsonify(response_with_buttons)

@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()