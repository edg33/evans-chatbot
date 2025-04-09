import os
import requests
from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload, text_upload, retrieve
from string import Template

# Rocket.Chat credentials
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
    return None

def rag_context_string(rag_context):
    context = ""
    for i, doc in enumerate(rag_context, 1):
        context += f"\n#{i}: {doc['doc_summary']}\n"
        for j, chunk in enumerate(doc['chunks'], 1):
            context += f"- {chunk}\n"
    return context

@app.route("/", methods=["POST"])
def handle_request():
    data = request.get_json()
    user = data.get("user_name", "Unknown")
    message = data.get("text", "")
    room_id = data.get("channel_id", "")

    # Handle file upload
    if "files" in data.get("message", {}):
        for file_info in data["message"]["files"]:
            file_id = file_info["_id"]
            filename = file_info["name"]
            local_path = download_file(file_id, filename)
            if local_path:
                if filename.endswith(".pdf"):
                    pdf_upload(path=local_path, session_id=user, strategy="smart")
                elif filename.endswith(".txt"):
                    with open(local_path, "r") as f:
                        text_upload(text=f.read(), session_id=user, strategy="smart")
        return jsonify({"text": "✅ File uploaded. What would you like to ask about it?"})

    # Handle question
    if message and not data.get("bot"):
        rag_context = retrieve(query=message, session_id=user, rag_threshold=0.2, rag_k=3)
        full_query = Template("$query\n\n$rag").substitute(
            query=message,
            rag=rag_context_string(rag_context)
        )
        response = generate(
            model="4o-mini",
            system="You are a helpful teaching assistant. Use the context to help answer the question.",
            query=full_query,
            temperature=0.3,
            lastk=0,
            session_id=user,
            rag_usage=False
        )
        return jsonify({"text": response["response"]})

    return jsonify({"status": "ignored"})

@app.errorhandler(404)
def not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()
