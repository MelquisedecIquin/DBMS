#Main system for the Account and Login system
from flask import Flask, request, jsonify
from flask_cors import CORS
import bcrypt
import re

app = Flask(__name__)
CORS(app)

user_db = {}

def is_valid_username(username):
    if len(username) < 6:
        return False, "Username must be at least 6 characters long."
    if not re.search(r"[A-Za-z]", username):
        return False, "Username must contain at least one letter."
    if not re.search(r"[0-9]", username):
        return False, "Username must contain at least one number."
    if not re.search(r"[!@#$%^&*]", username):
        return False, "Username must contain at least one special character (!@#$%^&*)."
    return True, "Valid username."

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    # Validate inputs
    valid, message = is_valid_username(username)
    if not valid:
        return jsonify({"message": message}), 400

    if username in user_db:
        return jsonify({"message": "Username already exists. Please choose another."}), 400

    if not password:
        return jsonify({"message": "Password cannot be empty."}), 400

    # Here where the hash password and store works
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    user_db[username] = hashed_pw

    return jsonify({"message": "Account created successfully!"}), 200

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if username not in user_db:
        return jsonify({"message": "Username does not exist."}), 400

    stored_hash = user_db[username]
    if bcrypt.checkpw(password.encode(), stored_hash):
        return jsonify({"message": f"Login successful! Welcome, {username}"}), 200
    else:
        return jsonify({"message": "Incorrect password."}), 400

if __name__ == "__main__":
    app.run(debug=True)
