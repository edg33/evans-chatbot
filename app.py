import requests
from flask import Flask, request, jsonify
from llmproxy import generate
import os
import random

app = Flask(__name__)

ID_VAL = random.randint(1,100000)

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
    global ID_VAL
    data = request.get_json() 

    # Extract relevant information
    user = data.get("user_name", "Unknown")
    second_agent = user + "_2"
    third_agent = user + "_3"
    examples_agent = user + "_examples"
    message = data.get("text", "")

    print(data)

    # Check for button clicks
    if "examples" in message:
        # Generate examples based on the last question from the bot
        examples_response = generate(
            model='4o-mini',
            system=(
                "You are a helpful assistant that provides concrete examples based on questions. "
                "When given a question, provide 3-4 realistic and varied examples based on the previous conversation "
                "of how someone might answer that question. Keep each example brief. "
                "Format each example with a bullet point."
            ),
            query=f"The user was asked to describe the vibe of their movie scene or to provide details about mood, lighting, etc. "
                 f"Generate 3-4  examples of possible answers to the question being posed. "
                 f"and showcase various film genres and moods.",
            temperature=0.7,  # Higher temperature for more creative examples
            lastk=0,
            session_id=examples_agent + f"_{ID_VAL}"
        )
        
        examples_text = examples_response["response"]
        return jsonify({"text": f"Here are some examples of how you could describe your scene:\n\n{examples_text}"})
    
    if message == "restart":
        ID_VAL = random.randint(1,100000)
        # Clear session
        return jsonify({
            "text": "Let's start over! Please describe the vibe of your movie scene."
        })

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message from {user} : {message}")
    
    # Generate a response using LLMProxy
    response = generate(
        model='4o-mini',
        system='You are an assistant to help movie makers determine what song \
        to put in their movie scene. If the question is unrelated to this topic \
        politely remind the user of your purpose. If it appears the user \
        has an ambiguous prompt or a greeting, greet the user and explain \
        your purpose. The user will provide a vibe for a scene and you will \
        help them determine what song to use. The questions should be straight to the point \
        do not give examples of the answer uNLESS they ask. Ask questions related to the \
        intended mood, lighting, length of scene etc, one by one so that the \
        user starts building an idea of what they want or have in mind.\
        after they go through a series of questions, ask them if they have anything else \
        they wat to add and if not, ask them how many songs they want \
        Do not provide more than 10 song recommendations. After they provide you answers \
        to your questions and if you are confident in your answer, provide the song and artist. \
        If you are not confident in your answer, ask more clarifying questions. After you provide songs \
        ask if they like them or if they want to change something. \
        If you are providing song recommendations, ask who they want to share these recommendations with \
        by requesting their first and last name.',
        query= f"query: {message}",
        temperature=0.0,
        lastk=10,
        session_id=user+ f"_{ID_VAL}"
    )
    
    recommendation_text = response["response"]
    
    # Extract the question being asked to use for examples later
    question_extraction = generate(
        model='4o-mini',
        system=(
            "You are helping identify questions in text. Extract only the most recent question "
            "that the assistant is asking the user about their movie scene. If there are multiple "
            "questions, focus on the main one related to describing the scene, mood, lighting, etc."
        ),
        query=f"Extract the main question from this text: {recommendation_text}",
        temperature=0.0,
        lastk=0,
        session_id=third_agent+ f"_{ID_VAL}"
    )
    
    current_question = question_extraction['response']
    
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
        session_id=second_agent+ f"_{ID_VAL}"
    )

    song_artists = extraction['response']
    song_artists = song_artists.split("///")
    
    # Extract recipient name if present
    recipient_extraction = generate(
        model='4o-mini',
        system=(
            "You are helping extract recipient information. If the text contains a question about "
            "who to share recommendations with and a response with a first and last name, extract "
            "that name. If no name is found, respond with 'no recipient'."
        ),
        query=f"Extract recipient name from: {message}. If there's a first and last name mentioned as "
              f"someone to share recommendations with, extract it. Otherwise respond with 'no recipient'.",
        temperature=0.0,
        lastk=0,
        session_id=user + "_recipient" + f"_{ID_VAL}"
    )
    
    recipient = recipient_extraction['response']
    
    # Boolean to keep track of things
    is_first = True
    
    # Search for URL only if a song is found
    if "no song" in song_artists[0].lower():
        final_response = f"{recommendation_text}"
    else:
        message_items = ""
        # Search for each song
        for song_artist in song_artists:
            # If first start the chain
            if is_first:
                url = google_search(song_artist)
                if url:
                    final_response = f"{recommendation_text}\n\n{song_artist}: {url}"
                    message_items += f"{song_artist}: {url}"
                else:
                    final_response = f"{recommendation_text}\n\n{song_artist}: (No link)"
                    message_items += f"{song_artist}: (No link)"
                is_first = False 
            else:
                url = google_search(song_artist)
                if url:
                    final_response += f"\n\n{song_artist}: {url}"
                    message_items += f"\n\n{song_artist}: {url}"
                else:
                    final_response += f"\n\n{song_artist}: (No link)"
                    message_items += f"\n\n{song_artist}: (No link)"
        
        # Only send to Rocket Chat if recipient is provided
        if recipient != "no recipient":
            # Format recipient for Rocket Chat (convert to username format)
            if " " in recipient:
                firstname, lastname = recipient.split(" ", 1)
                recipient_username = f"@{firstname.lower()}.{lastname.lower()}"
            else:
                # If only one name is provided, use it as is
                recipient_username = f"@{recipient.lower()}"
            
            # API endpoint
            endpoint = "https://chat.genaiconnect.net/api/v1/chat.postMessage"
            # Headers with authentication tokens
            headers = {
                "Content-Type": "application/json",
                "X-Auth-Token": os.environ.get("RC_token"),
                "X-User-Id": os.environ.get("RC_userId")
            }
            # Payload (data to be sent)
            payload = {
                "channel": recipient_username,
                "text": f"What do you think of these songs for your scene with {user}?\n\n" + message_items
            }
            
            # Sending the POST request
            response = requests.post(endpoint, json=payload, headers=headers)
            
            # Check if the message was sent successfully
            if response.status_code == 200:
                final_response += f"\n\nRecommendations sent to {recipient}!"
            else:
                final_response += f"\n\nCould not send recommendations to {recipient}. User may not exist in Rocket Chat."
            
            # Print response status and content
            print(response.status_code)
            print(response.json())
    
    # Add examples/restart buttons to the response
    response_with_buttons = {
        "text": final_response,
        "attachments": [
            {
                "text": "What would you like to do?",
                "actions": [
                    {
                        "type": "button",
                        "text": "Examples",
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
    
    print(f"Final Response: {final_response}")
    return jsonify(response_with_buttons)
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()