import os
import requests
from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload, text_upload, retrieve
from string import Template

# Rocket.Chat settings
ROCKET_CHAT_URL = os.environ.get("RC_URL", "https://chat.genaiconnect.net")
ROCKET_USER_ID = os.environ.get("RCuser")
ROCKET_AUTH_TOKEN = os.environ.get("RCtoken")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

app = Flask(__name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)
            return local_path
    print(f"Download error {filename} - {response.status_code}")
    return None

def rag_context_string_simple(rag_context):
    context_string = ""
    i = 1
    for collection in rag_context:
        if not context_string:
            context_string = "Here is some context from your uploaded files:\n"
        context_string += f"\n#{i} {collection['doc_summary']}\n"
        for j, chunk in enumerate(collection['chunks'], start=1):
            context_string += f"#{i}.{j} {chunk}\n"
        i += 1
    return context_string

def google_search(query, site_filter="youtube.com"):
    """Queries Google Search API and returns the first YouTube result link."""
    search_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": os.environ.get("GOOGLE_API_KEY"),
        "cx": os.environ.get("GOOGLE_CSE_ID"),
        "q": f"{query} site:{site_filter}",
        "num": 1
    }
    response = requests.get(search_url, params=params)
    if response.status_code == 200:
        results = response.json().get("items", [])
        if results:
            return results[0]["link"]
    print(f"Search error: {response.status_code}, {response.text}")
    return None

@app.route("/", methods=["POST"])
def handle_request():
    data = request.get_json()
    user = data.get("user_name", "Unknown")
    message = data.get("text", "")
    room_id = data.get("channel_id", "")

    # Ignore bot messages
    if data.get("bot") or (not message and "files" not in data.get("message", {})):
        return jsonify({"status": "ignored"})

    # Handle file uploads
    if "files" in data.get("message", {}):
        saved_files = []
        for file_info in data["message"]["files"]:
            file_id = file_info["_id"]
            filename = file_info["name"]
            local_path = download_file(file_id, filename)
            if local_path:
                # Upload to LLMProxy
                if filename.endswith(".pdf"):
                    pdf_upload(path=local_path, session_id=user, strategy="smart")
                elif filename.endswith(".txt"):
                    with open(local_path, "r") as f:
                        text_upload(text=f.read(), session_id=user, strategy="smart")
                saved_files.append(filename)

        file_list = "\n".join(f"- {f}" for f in saved_files)
        return jsonify({
            "text": f"✅ File(s) uploaded successfully:\n{file_list}\n\nWhat would you like help with in the file?"
        })

    # Otherwise, handle normal user query
    # Retrieve RAG context (if any files uploaded before)
    rag_context = retrieve(query=message, session_id=user, rag_threshold=0.2, rag_k=3)
    context_str = rag_context_string_simple(rag_context)

    full_prompt = Template("$query\n\n$rag_context").substitute(
        query=message,
        rag_context=context_str
    )

    # Generate thoughtful TA response
    ta_response = generate(
        model="4o-mini",
        system=(
            "You are a helpful TA for an algorithms and data structures class. "
            "Use uploaded content to help the student, but don't just give away answers. "
            "Ask clarifying or guiding questions. Include video resources if the query is algorithm-related."
        ),
        query=full_prompt,
        temperature=0.4,
        lastk=5,
        session_id=user,
        rag_usage=False
    )

    answer = ta_response["response"]

    # Check if it’s an algorithm question and attach video if so
    alg_check = generate(
        model="4o-mini",
        system="Is this about an algorithm or data structure? Reply 'yes' or 'no'.",
        query=message,
        temperature=0.0,
        lastk=0,
        session_id=user + "_alg_check"
    )
    if alg_check["response"].strip().lower() == "yes":
        link = google_search(message)
        if link:
            answer += f"\n\n🔗 You might also find this helpful: {link}"

    return jsonify({
        "text": answer,
        "attachments": [
            {
                "text": "What would you like to do next?",
                "actions": [
                    {
                        "type": "button",
                        "text": "Try another explanation",
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
    })

@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()
