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
    message = data.get("text", "")

    print(data)

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message from {user} : {message}")
    
    url = google_search(message)

    # Generate a response using LLMProxy
    response = generate(
        model='4o-mini',
        system='You are an assistant to help individuals navigate their \
        questions about life in Somerville, Massachusetts. These questions \
        might be related to parking, waste removal or municipal events.\
        If an individual \
        asks a question that is unrelated to information that might be found \
        on the municipal website politely remind them that you cannot answer \
        such questions. If you have the information to answer the query, \
        provide it. If there is a URL in the query, provide it after your \
        answer so the user can learn more on the website.\
        If the question is unrelated to Somerville, do not provide the url',
        query= f"query: {message}, url:{url}",
        temperature=0.0,
        lastk=0,
        session_id='GenericSession'
    )

    response_text = response['response']
    
    # Send response back
    print(response_text)

    return jsonify({"text": response_text})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()