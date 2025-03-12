import requests
import os
import time
from flask import Flask, request, jsonify, abort
from llmproxy import generate, retrieve, text_upload
from string import Template

app = Flask(__name__)

# Global variables
ROCKET_CHAT_URL = "https://chat.genaiconnect.net"
ROCKET_USER_ID = os.environ.get("RC_userId")
ROCKET_AUTH_TOKEN = os.environ.get("RC_token")

# File handling
UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def download_file(file_id, filename):
    """Download file from Rocket.Chat and save locally."""
    if allowed_file(filename):
        file_url = f"{ROCKET_CHAT_URL}/file-upload/{file_id}/{filename}"
        headers = {
            "X-User-Id": ROCKET_USER_ID,
            "X-Auth-Token": ROCKET_AUTH_TOKEN
        }

        response = requests.get(file_url, headers=headers, stream=True)
        if response.status_code == 200:
            local_path = os.path.join(UPLOAD_FOLDER, filename)
            with open(local_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            return local_path
    
    print(f"INFO - some issue with {filename} with {response.status_code} code")
    return None

def extract_text_from_file(file_path):
    """Extract text from different file types."""
    ext = file_path.split('.')[-1].lower()
    
    if ext == 'txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return "Unsupported file format."

def google_search(query):
    """Queries Google Search API and returns the first result link."""
    search_url = "https://www.googleapis.com/customsearch/v1"
    
    params = {
        "key": os.environ.get("GOOGLE_API_KEY"),
        "cx": os.environ.get("GOOGLE_CSE_ID"),
        "q": query,
        "num": 1
    }
    
    response = requests.get(search_url, params=params)
    
    if response.status_code == 200:
        search_results = response.json().get("items", [])
        if search_results:
            return search_results[0]["link"]
    print(f"Error: {response.status_code}, {response.text}")
    return None

def rag_context_string(rag_context):
    """Format RAG context for the LLM."""
    context_string = ""

    i = 1
    for collection in rag_context:
        if not context_string:
            context_string = "The following is additional context from the script that may be helpful in recommending songs for the scene:"

        context_string += f"\n#{i} {collection.get('doc_summary', 'Document chunk')}\n"
        j = 1
        for chunk in collection.get('chunks', []):
            context_string += f"#{i}.{j} {chunk}\n"
            j += 1
        i += 1
    return context_string

def analyze_script_agentic(script_text, user_id):
    """Use an agentic workflow to analyze the script and recommend songs."""
    session_id = f"{user_id}_script_analysis"
    qa_session_id = f"{user_id}_script_qa"
    recommendation_session_id = f"{user_id}_script_recommendation"
    
    # First agent: Script analyzer that extracts key information
    analyzer_response = generate(
        model='4o-mini',
        system="""You are an expert script analyzer. Your task is to examine the provided movie/scene script 
        and extract key information that would be relevant for song selection, including:
        1. Setting and time period
        2. Mood and emotional tone
        3. Character dynamics
        4. Key themes or motifs
        5. Pace and rhythm of the scene
        6. Any specific musical cues mentioned
        Format your analysis clearly and concisely, focusing on elements that would influence music selection.""",
        query=f"Here is a script or scene description to analyze:\n\n{script_text}",
        temperature=0.3,
        lastk=5,
        session_id=session_id
    )
    
    analysis = analyzer_response["response"]
    
    # Second agent: Generate questions and answers about the script
    qa_response = generate(
        model='4o-mini',
        system="""You are a music supervisor for films. Based on the script analysis provided, 
        generate 5 important questions you would normally ask a director about their musical preferences for this scene. 
        Then, using just the script analysis, provide likely answers to those questions. 
        Format as Question 1: [question] Answer: [answer], etc.""",
        query=f"Based on this script analysis, generate key questions and their likely answers:\n\n{analysis}",
        temperature=0.4,
        lastk=5,
        session_id=qa_session_id
    )
    
    qa_pairs = qa_response["response"]
    
    # Third agent: Generate song recommendations
    recommendation_response = generate(
        model='4o-mini',
        system="""You are a professional music supervisor for films. Based on the script analysis and Q&A provided,
        recommend 3-5 songs that would work well for this scene. For each song, provide:
        1. Song title and artist
        2. A brief explanation of why this song fits the scene
        3. How the song's mood, tempo, and lyrics (if applicable) enhance the scene's emotional impact
        
        Consider varied artists and styles to give options. Focus on providing songs that authentically enhance
        the scene rather than just popular hits.""",
        query=f"Based on this script analysis and Q&A, recommend appropriate songs for the scene:\n\nANALYSIS:\n{analysis}\n\nQ&A:\n{qa_pairs}",
        temperature=0.7,
        lastk=5,
        session_id=recommendation_session_id
    )
    
    # Format final output to include the entire thought process
    final_output = f"""
                    Script Analysis:
                    {analysis}

                    Questions and Answers I considered:
                    {qa_pairs}

                    Song Recommendations:
                    {recommendation_response["response"]}
                    """
    
    return final_output

def send_message_with_file(room_id, message, file_path):
    """Send a message with a file to Rocket.Chat."""
    url = f"{ROCKET_CHAT_URL}/api/v1/rooms.upload/{room_id}"
    headers = {
        "X-User-Id": ROCKET_USER_ID,
        "X-Auth-Token": ROCKET_AUTH_TOKEN
    }
    files = {"file": (os.path.basename(file_path), open(file_path, "rb"))}
    data = {"msg": message}

    response = requests.post(url, headers=headers, files=files, data=data)
    if response.status_code != 200:
        return {"error": f"Failed to upload file, Status Code: {response.status_code}, Response: {response.text}"}
    try:
        return response.json()
    except requests.exceptions.JSONDecodeError:
        return {"error": "Invalid JSON response from Rocket.Chat API", "raw_response": response.text}

@app.route('/', methods=['POST'])
def handle_request():
    data = request.get_json()
    
    # Validate data
    if not data:
        return jsonify({"error": "Invalid request format"}), 400

    # Extract relevant information
    user = data.get("user_name", "Unknown")
    user_id = data.get("user_id", f"user_{int(time.time())}")
    room_id = data.get("channel_id", "")
    message = data.get("text", "")

    print(f"Received data: {data}")

    # Check if this is a button action
    if "examples" in message:
        examples_response = generate(
            model='4o-mini',
            system=(
                "You are a helpful assistant that provides concrete examples based on questions. "
                "When given a question, provide 3-4 realistic and varied examples of how someone might answer that question. "
                "Keep each example brief. Format each example with a bullet point."
            ),
            query="The user was asked to describe the vibe of their movie scene or to provide details about mood, lighting, etc. "
                 "Generate 3-4 examples of possible answers to the question being posed and showcase various film genres and moods.",
            temperature=0.7,
            lastk=0,
            session_id=f"{user}_examples"
        )
        
        examples_text = examples_response["response"]
        return jsonify({"text": f"Here are some examples of how you could describe your scene:\n\n{examples_text}"})
    
    if message == "restart":
        return jsonify({
            "text": "Let's start over! Please describe the vibe of your movie scene or upload a script file."
        })
    
    if message == "analyze_script":
        return jsonify({
            "text": "Please upload a script file (TXT) and I'll analyze it to recommend songs."
        })

    # Handle file upload - improved handling based on second example
    if ("message" in data) and ('file' in data['message']):
        print(f"File detected in message")
        saved_files = []

        for file_info in data["message"]["files"]:
            file_id = file_info["_id"]
            filename = file_info["name"]
            
            # Download file
            file_path = download_file(file_id, filename)
            
            if file_path:
                saved_files.append(file_path)
                
                # Extract text from the file if it's a document type
                ext = filename.split('.')[-1].lower()
                if ext in ['txt', 'pdf', 'docx', 'doc']:
                    # Extract text from the file
                    script_text = extract_text_from_file(file_path)
                    
                    # Upload the script text to RAG
                    rag_response = text_upload(
                        text=script_text,
                        session_id=f"{user_id}_RAG",
                        strategy='fixed'
                    )
                    
                    time.sleep(10)  # Wait for indexing
                    
                    # Analyze the script using agentic approach
                    analysis_result = analyze_script_agentic(script_text, user_id)
                    
                    # Extract songs from the analysis
                    song_extraction = generate(
                        model='4o-mini',
                        system="Extract only the song titles and artists from the provided text. Format as 'Song - Artist'. If there are multiple songs, separate them with '///'.",
                        query=f"Extract songs from: {analysis_result}",
                        temperature=0.0,
                        lastk=0,
                        session_id=f"{user_id}_extractor"
                    )
                    
                    songs = song_extraction["response"].split("///")
                    
                    # Add links to songs
                    song_links = []
                    for song in songs:
                        if song.strip():
                            url = google_search(song.strip())
                            if url:
                                song_links.append(f"{song.strip()}: {url}")
                            else:
                                song_links.append(f"{song.strip()}: (No link)")
                    
                    # Ask who to share with
                    share_question = "Who would you like to share these song recommendations with? Please provide their first and last name."
                    
                    final_response = f"Based on your script, I've analyzed it and generated song recommendations:\n\n{analysis_result}\n\n"
                    final_response += "Here are links to the recommended songs:\n\n"
                    final_response += "\n\n".join(song_links)
                    final_response += f"\n\n{share_question}"
                    
                    return jsonify({
                        "text": final_response,
                        "attachments": [
                            {
                                "text": "What would you like to do next?",
                                "actions": [
                                    {
                                        "type": "button",
                                        "text": "Get More Recommendations",
                                        "msg": "analyze_script",
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
                    })
                else:
                    # For non-script files, just acknowledge receipt
                    return jsonify({
                        "text": f"File '{filename}' received. Please upload a script file (PDF, TXT, or DOCX) for analysis.",
                        "attachments": [
                            {
                                "text": "What would you like to do?",
                                "actions": [
                                    {
                                        "type": "button",
                                        "text": "Analyze Script",
                                        "msg": "analyze_script",
                                        "msg_in_chat_window": True,
                                        "msg_processing_type": "sendMessage"
                                    }
                                ]
                            }
                        ]
                    })
            else:
                return jsonify({"error": "Failed to download file"}), 500

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message from {user}: {message}")
    
    # Extract recipient if present (for sharing recommendations)
    recipient_extraction = generate(
        model='4o-mini',
        system=(
            "You are helping extract recipient information. If the text contains a first and last name as "
            "a response to who to share recommendations with, extract that name. "
            "If no name is found, respond with 'no recipient'."
        ),
        query=f"Extract recipient name from: {message}. If there's a first and last name mentioned as "
              f"someone to share recommendations with, extract it. Otherwise respond with 'no recipient'.",
        temperature=0.0,
        lastk=0,
        session_id=f"{user}_recipient"
    )
    
    recipient = recipient_extraction["response"]
    
    # Check if the user wants to use the RAG context (have they uploaded a script)
    use_rag = False
    try:
        rag_context = retrieve(
            query=message,
            session_id=f"{user_id}_RAG",
            rag_threshold=0.2,
            rag_k=3
        )
        if rag_context:
            use_rag = True
    except Exception as e:
        print(f"RAG retrieval error: {e}")
        use_rag = False
    
    # Generate a response using LLMProxy
    if use_rag:
        # Format context from RAG
        context_string = rag_context_string(rag_context)
        
        # Generate with context from the uploaded script
        query_with_context = Template("$query\n$context").substitute(
            query=message,
            context=context_string
        )
        
        system_prompt = """You are an assistant to help movie makers determine what song to put in their movie scene.
        You have been provided with context from a script that the user uploaded.
        If the question is unrelated to this topic, politely remind the user of your purpose.
        Based on the script context and the user's input, help determine appropriate songs for the scene.
        After providing song recommendations, ask if they like them or if they want to change something.
        If you are providing song recommendations, ask who they want to share these recommendations with
        by requesting their first and last name."""
        
        response = generate(
            model='4o-mini',
            system=system_prompt,
            query=query_with_context,
            temperature=0.0,
            lastk=5,
            session_id=user
        )
    else:
        # Standard response without RAG
        system_prompt = """You are an assistant to help movie makers determine what song to put in their movie scene.
        If the question is unrelated to this topic, politely remind the user of your purpose.
        If it appears the user has an ambiguous prompt or a greeting, greet the user and explain your purpose.
        The user will provide a vibe for a scene and you will help them determine what song to use.
        The questions should be straight to the point. Do not give examples of the answer UNLESS they ask.
        Ask questions related to the intended mood, lighting, length of scene etc, one by one so that the
        user starts building an idea of what they want or have in mind.
        After they go through a series of questions, ask them if they have anything else they want to add
        and if not, ask them how many songs they want. Do not provide more than 10 song recommendations.
        After they provide you answers to your questions and if you are confident in your answer,
        provide the song and artist. If you are not confident in your answer, ask more clarifying questions.
        After you provide songs, ask if they like them or if they want to change something.
        If you are providing song recommendations, ask who they want to share these recommendations with
        by requesting their first and last name.
        
        If the user is asking to analyze a script, inform them they can upload a script file (PDF, TXT, or DOCX)
        and you'll analyze it to recommend songs automatically."""
        
        response = generate(
            model='4o-mini',
            system=system_prompt,
            query=message,
            temperature=0.0,
            lastk=5,
            session_id=user
        )
    
    recommendation_text = response["response"]
    
    # Extract songs from the response
    song_extraction = generate(
        model='4o-mini',
        system=(
            "You are helping a second agent. Extract only the song and artist from the provided text. "
            "Remove everything that is not the key song and artist. "
            "If none are found, respond with 'no song'."
        ),
        query=f"Extract song and artist from: {recommendation_text}. "
              f"Remove everything that is not a song and artist pair. "
              f"If there are multiple song and artist pairs, separate the "
              f"responses with '///'",
        temperature=0.0,
        lastk=0,
        session_id=f"{user}_song_extractor"
    )

    song_artists = song_extraction["response"].split("///")
    
    # Boolean to keep track of things
    is_first = True
    
    # Search for URL only if a song is found
    if "no song" in song_artists[0].lower():
        final_response = recommendation_text
    else:
        message_items = ""
        # Search for each song
        for song_artist in song_artists:
            if not song_artist.strip():
                continue
                
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
            endpoint = f"{ROCKET_CHAT_URL}/api/v1/chat.postMessage"
            # Headers with authentication tokens
            headers = {
                "Content-Type": "application/json",
                "X-Auth-Token": ROCKET_AUTH_TOKEN,
                "X-User-Id": ROCKET_USER_ID
            }
            # Payload (data to be sent)
            payload = {
                "channel": recipient_username,
                "text": f"What do you think of these songs for your scene with {user}?\n\n{message_items}"
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
            try:
                print(response.json())
            except:
                print("Could not parse JSON response")
    
    # Add special buttons based on content
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
                        "text": "Analyze Script",
                        "msg": "analyze_script",
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