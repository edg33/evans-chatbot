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
    
    #url = google_search(message)

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
        intended mood, lighting, length of scene etc. Make sure to ask how\
        many songs the user wants. Do not provide more than 10 song \
        recommendations. After some questions, \
        if you are confident in your answer, provide the song and artist. \
        If you are not confident in your answer, ask more clarifying questions.',
        query= f"query: {message}",
        temperature=0.0,
        lastk=5,
        session_id=user
    )
    
    recommendation_text = response["response"]
    
    # Gets the song and artist so it can be searched
    extraction = generate(
        model='4o-mini',
        system=(
            "You are helping a second agent. Extract only the song and artist from the provided text. \
             Remove everything that is not the key song and artist. \
             If none are found, respond with 'no song'."
        ),
        query=f"Extract song and artist from: {recommendation_text}.\
                Remove everything that is not the a song and artist pair.\
                If there are multiple song and artist pairs, separate the \
                responses with \'///\'",
        temperature=0.0,
        lastk=0,
        session_id=second_agent
    )

    song_artists = extraction['response']
    song_artists = song_artists.split("///")
    
    # Boolean to keep track of things
    is_first = True
    
    # print(f"Extracted Song and Artist: {song_artist}")
    # Search for URL only if a song is found
    if "no song" in song_artists[0].lower():
        # final_response = f"{recommendation_text}\n\n(No song recommendation provided.)"
        final_response = f"{recommendation_text}"
    else:
        # Search for each song
        for song_artist in song_artists:
            # If first start the chain
            if is_first:
                url = google_search(song_artist)
                if url:
                    final_response = f"{recommendation_text}\n\n{song_artist}: {url}"
                else:
                    final_response = f"{recommendation_text}\n\n{song_artist}:(No link)"
                is_first = False 
            else:
                url = google_search(song_artist)
                if url:
                    final_response += f"\n\n{song_artist}: {url}"
                else:
                    final_response += f"\n\n{song_artist}:(No link)"
    
    # API endpoint
    endpoint = "https://chat.genaiconnect.net/api/v1/chat.postMessage" #URL of RocketChat server, keep the same

    # Headers with authentication tokens
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": os.environ.get("RC_token"), #Replace with your bot token for local testing or keep it and store secrets in Koyeb
        "X-User-Id": os.environ.get("RC_userId")#Replace with your bot user id for local testing or keep it and store secrets in Koyeb
    }

    # Payload (data to be sent)
    payload = {
        "channel": "@juliana.alscher", #Change this to your desired user, for any user it should start with @ then the username
        "text": "This is a direct message from the bot" #This where you add your message to the user
    }

    # Sending the POST request
    response = requests.post(endpoint, json=payload, headers=headers)

    # Print response status and content
    print(response.status_code)
    print(response.json())  
    
    # final_response = final_response + f"\n\n {extraction["response"]}"

    print(f"Final Response: {final_response}")
    return jsonify({"text": final_response})


    
    
    # # Send response back
    # print(response_text_3)
    # 
    # return jsonify({"text": response_text_3})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()