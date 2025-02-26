import requests
from flask import Flask, request, jsonify
from llmproxy import generate
import os

app = Flask(__name__)

def google_search(query):
    """Queries Google Search API and returns the first result link."""
    search_url = "https://www.googleapis.com/customsearch/v1"
    
    params = {
        "key": os.environ.get("GOOGLE_API_KEY"),
        "cx": os.environ.get("GOOGLE_CSE_ID"),
        "q": query,
        "num": 1  # Might change this
    }
    
    response = requests.get(search_url, params=params)
    
    if response.status_code == 200:
        search_results = response.json().get("items", [])
        if search_results:
            return search_results[0]["link"]  # Return only the first result
    print(f"Error: {response.status_code}, {response.text}")
    return None

@app.route('/', methods=['POST'])
def handle_request():
    data = request.get_json() 

    # Extract relevant information
    user = data.get("user_name", "Unknown")
    second_agent = user + "_2"
    third_agent = user+ "_3"
    message = data.get("text", "")

    print(data)

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message from {user} : {message}")
    
    url = google_search(message)

    # Generate a response using LLMProxy
    # Adjust this so that it uses multiple responses.
    # Use the web pages
    response = generate(
        model='4o-mini',
        system='You are an assistant to help movie makers determine what song \
        to put in their scene. If the question is unrelated to this topic \
        politely remind the user of your purpose. If it appears the user \
        has an ambiguous prompt or a greeting, greet the user and explain \
        your purpose. The user will provide a vibe for a scene and you will \
        help them determine what song to use. Ask questions related to the \
        intended mood, lighting, length of scene etc. After some questions, \
        if you are confident in your answer, provide the url from the query.',
        query= f"query: {message}, url:{url}. Only show the url if you \
        are confident in the recommendation.",
        temperature=0.0,
        lastk=5,
        session_id=user
    )
    
    # Gets the song and artist so it can be searched
    response_2 = generate(
        model='4o-mini',
        system='You are helping a second agent. Do not provide any information\
         or acknowledgements of your task. Strictly perform the task outlined \
         in the query.',
        query= f"Filter this: {response['response']} such that the only text \
        in your output is the name of the song and the artist. If there is no \
        song included in that information, default to Never Gonna Give You Up \
        by Rick Astley.",
        temperature=0.0,
        lastk=0,
        session_id=second_agent
    )
    url = google_search(response_2['response'])
    
    response_text = response['response']
    
    # Replaces the link with a working one
    response_3 = generate(
        model='4o-mini',
        system='You are to clean up a different response. Only change the link \
        if a link is provided in the response. Do not say anything aside from \
        cleaning the response.',
        query= f"If there is a link provided in the response: ({response}), \
        replace it with the following url: {url}",
        temperature=0.0,
        lastk=0,
        session_id=third_agent
    )
    response_text_3 = response_3['response']
    
    # Send response back
    print(response_text_3)

    return jsonify({"text": response_text_3})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()