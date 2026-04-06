import re
import bcrypt
import getpass

user_db = {}

def is_valid_username(username):
    if len(username) < 6:   # changed from != 6
        return False, "Username must be at least 6 characters long."
    if not re.search(r"[A-Za-z]", username):
        return False, "Username must contain at least one letter."
    if not re.search(r"[0-9]", username):
        return False, "Username must contain at least one number."
    if not re.search(r"[!@#$%^&*]", username):
        return False, "Username must contain at least one special character (!@#$%^&*)."
    return True, "Valid username."

def signup():
    while True:
        username = input("Enter a new username: ")
        valid, message = is_valid_username(username)
        if not valid:
            print("Error:", message)
            continue
        if username in user_db:
            print("Warning: Username is already used. Please choose another.")
            continue
        # Hide password input
        password = getpass.getpass("Enter a password (hidden): ")
        hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        user_db[username] = hashed_pw
        print("Account created successfully!")
        break

def login():
    username = input("Enter your username: ")
    if username not in user_db:
        print("Error: Username does not exist.")
        return
    # Hide password input
    password = getpass.getpass("Enter your password (hidden): ")
    stored_hash = user_db[username]
    if bcrypt.checkpw(password.encode(), stored_hash):
        print("Login successful! Welcome,", username)
    else:
        print("Error: Incorrect password.")

def main_menu():
    while True:
        print("\n ___ Account System ___")
        print("1. Sign Up")
        print("2. Log In")
        print("3. Exit")
        choice = input("Choose an option: ")

        if choice == "1":
            signup()
        elif choice == "2":
            login()
        elif choice == "3":
            print("Exiting... Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main_menu()
