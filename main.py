#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import threading
import time
import os
import shutil
import json
import requests
from flask import Flask, send_from_directory, request, jsonify, abort

# IMPORTANT: You need to install Flask for this program to work.
# Open your terminal and run: pip install Flask

class CollabCX(tk.Tk):
    """
    CollabCX is a file and real-time chat collaboration application.
    It allows users to create a new collaboration or join an existing one.
    """
    def __init__(self):
        super().__init__()
        self.title("CollabCX - Collaborate with Love")
        self.geometry("800x600")
        self.config(bg="#f0f2f5")

        self.server_thread = None
        self.app = None
        self.sync_thread = None
        self.stop_server_event = threading.Event()
        self.is_owner = False
        self.collaboration_path = ""
        self.collaboration_name = ""
        self.chat_history = []
        self.lock = threading.Lock() # To safely handle access to shared data

        self.create_widgets()

    def create_widgets(self):
        """
        Creates the user interface for the application.
        """
        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        style = ttk.Style()
        style.configure("TFrame", background="#f0f2f5")
        style.configure("TButton", font=("Helvetica", 12), padding=10)
        style.configure("TLabel", background="#f0f2f5", font=("Helvetica", 14))

        title_label = ttk.Label(main_frame, text="Welcome to CollabCX", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)

        desc_label = ttk.Label(main_frame, text="Choose an option to start collaborating with love.", font=("Helvetica", 16))
        desc_label.pack(pady=10)

        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=20)

        create_button = ttk.Button(button_frame, text="Create Collaboration", command=self.create_collaboration_view)
        create_button.pack(side="left", padx=10)

        join_button = ttk.Button(button_frame, text="Join Collaboration", command=self.join_collaboration_view)
        join_button.pack(side="left", padx=10)

    def create_collaboration_view(self):
        """
        Displays the interface to create a collaboration.
        """
        self.clear_frame(self)
        self.is_owner = True

        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        title_label = ttk.Label(main_frame, text="Create a New Collaboration", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)

        path_label = ttk.Label(main_frame, text="Select the project folder:")
        path_label.pack(pady=(10, 5))

        self.path_entry = ttk.Entry(main_frame, width=50)
        self.path_entry.pack(pady=5)

        browse_button = ttk.Button(main_frame, text="Browse Folder", command=self.select_folder)
        browse_button.pack(pady=5)

        start_button = ttk.Button(main_frame, text="Start Collaboration", command=self.start_collaboration)
        start_button.pack(pady=20)

        back_button = ttk.Button(main_frame, text="Back", command=self.back_to_main)
        back_button.pack(pady=5)

    def join_collaboration_view(self):
        """
        Displays the interface to join a collaboration.
        """
        self.clear_frame(self)
        self.is_owner = False

        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        title_label = ttk.Label(main_frame, text="Join a Collaboration", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)

        server_label = ttk.Label(main_frame, text="Enter the server address (URL):")
        server_label.pack(pady=(10, 5))

        self.server_entry = ttk.Entry(main_frame, width=50)
        self.server_entry.pack(pady=5)

        join_button = ttk.Button(main_frame, text="Join", command=self.join_collaboration)
        join_button.pack(pady=20)

        back_button = ttk.Button(main_frame, text="Back", command=self.back_to_main)
        back_button.pack(pady=5)

    def select_folder(self):
        """
        Opens a dialog for the user to select a folder.
        """
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder_path)

    def start_collaboration(self):
        """
        Starts the collaboration as the owner.
        """
        self.collaboration_path = self.path_entry.get()
        if not os.path.isdir(self.collaboration_path):
            messagebox.showerror("Error", "The folder path is not valid.")
            return

        self.collaboration_name = os.path.basename(self.collaboration_path)
        self.stop_server_event.clear()

        # Start the Flask server in a separate thread
        self.server_thread = threading.Thread(target=self.run_flask_server)
        self.server_thread.daemon = True
        self.server_thread.start()

        self.open_collaboration_window()

    def join_collaboration(self):
        """
        Joins an existing collaboration.
        """
        server_url = self.server_entry.get()
        if not server_url:
            messagebox.showerror("Error", "Please enter a server URL.")
            return

        # Check if it's a CollabCX collaboration
        try:
            response = requests.get(f"{server_url}/verify")
            if response.status_code == 200 and response.json().get("status") == "CollabCX":
                collaboration_name = response.json().get("name")
                self.collaboration_name = collaboration_name
                self.collaboration_path = os.path.join(os.getcwd(), collaboration_name)

                # Create the folder if it doesn't exist and download the files
                if not os.path.exists(self.collaboration_path):
                    os.makedirs(self.collaboration_path)

                self.server_url = server_url
                self.sync_thread = threading.Thread(target=self.sync_client_files)
                self.sync_thread.daemon = True
                self.sync_thread.start()
                self.open_collaboration_window()
            else:
                messagebox.showerror("Error", "This is not a valid CollabCX server.")
        except requests.exceptions.RequestException:
            messagebox.showerror("Error", "Could not connect to the server. Check the URL.")

    def run_flask_server(self):
        """
        Configures and runs the Flask server.
        """
        self.app = Flask(__name__)

        @self.app.route("/verify")
        def verify():
            return jsonify({"status": "CollabCX", "name": self.collaboration_name})

        @self.app.route("/<path:filename>")
        def get_file(filename):
            return send_from_directory(self.collaboration_path, filename)

        @self.app.route("/list_files")
        def list_files():
            files = []
            for root, dirs, filenames in os.walk(self.collaboration_path):
                for filename in filenames:
                    rel_path = os.path.relpath(os.path.join(root, filename), self.collaboration_path)
                    files.append(rel_path)
            return jsonify(files)

        @self.app.route("/chat", methods=["GET", "POST"])
        def chat_endpoint():
            if request.method == "POST":
                with self.lock:
                    message = request.json.get("message")
                    self.chat_history.append(message)
                return "OK"
            else:
                with self.lock:
                    return jsonify(self.chat_history)

        @self.app.route("/stop", methods=["POST"])
        def stop_server():
            func = request.environ.get("werkzeug.server.shutdown")
            if func is None:
                raise RuntimeError("Not running with the Werkzeug server")
            func()
            return "Server stopping..."

        try:
            # You can change the port if you need to
            self.app.run(port=5000)
        except Exception as e:
            messagebox.showerror("Server Error", f"Error starting the server: {e}")
            self.stop_server_event.set()

    def sync_client_files(self):
        """
        Synchronizes client files with the server.
        """
        while not self.stop_server_event.is_set():
            try:
                response = requests.get(f"{self.server_url}/list_files")
                if response.status_code == 200:
                    server_files = set(response.json())
                    local_files = set()

                    for root, dirs, filenames in os.walk(self.collaboration_path):
                        for filename in filenames:
                            rel_path = os.path.relpath(os.path.join(root, filename), self.collaboration_path)
                            local_files.add(rel_path)

                    # Download new or updated files
                    for file in server_files - local_files:
                        self.download_file(file)

                    # Delete files that no longer exist on the server
                    for file in local_files - server_files:
                        os.remove(os.path.join(self.collaboration_path, file))

                # Sync chat
                self.sync_chat()

            except requests.exceptions.RequestException:
                if not self.is_owner:
                    messagebox.showinfo("Collaboration Ended", "The owner has stopped the collaboration. Your folder will be deleted.")
                    shutil.rmtree(self.collaboration_path, ignore_errors=True)
                    self.stop_server_event.set()
                    self.back_to_main()

            time.sleep(2) # Wait 2 seconds for the next sync

    def download_file(self, filename):
        """
        Downloads a file from the server.
        """
        try:
            response = requests.get(f"{self.server_url}/{filename}")
            if response.status_code == 200:
                full_path = os.path.join(self.collaboration_path, filename)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "wb") as f:
                    f.write(response.content)
        except requests.exceptions.RequestException:
            pass

    def sync_chat(self):
        """
        Synchronizes the chat history with the server.
        """
        if self.is_owner:
            with self.lock:
                current_chat = list(self.chat_history)
        else:
            try:
                response = requests.get(f"{self.server_url}/chat")
                if response.status_code == 200:
                    current_chat = response.json()
                else:
                    current_chat = []
            except requests.exceptions.RequestException:
                current_chat = []

        self.update_chat_display(current_chat)

    def send_chat_message(self, event=None):
        """
        Sends a new message to the chat.
        """
        message = self.chat_input.get()
        if not message:
            return

        if self.is_owner:
            with self.lock:
                self.chat_history.append(f"Owner: {message}")
        else:
            try:
                requests.post(f"{self.server_url}/chat", json={"message": f"Collaborator: {message}"})
            except requests.exceptions.RequestException:
                messagebox.showerror("Error", "Could not send the message. The server is not responding.")

        self.chat_input.delete(0, tk.END)
        self.sync_chat()

    def update_chat_display(self, messages):
        """
        Updates the chat text widget with new messages.
        """
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.delete(1.0, tk.END)
        for msg in messages:
            self.chat_text.insert(tk.END, msg + "\n")
        self.chat_text.config(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def open_collaboration_window(self):
        """
        Opens the collaboration window with chat and details.
        """
        self.clear_frame(self)

        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        title_text = f"Collaboration: {self.collaboration_name}"
        title_label = ttk.Label(main_frame, text=title_text, font=("Helvetica", 24, "bold"))
        title_label.pack(pady=10)

        # If the user is the owner, show server information
        if self.is_owner:
            ip_addr = "127.0.0.1:5000"
            server_info_label = ttk.Label(main_frame, text=f"Server started at: http://{ip_addr}", font=("Helvetica", 12))
            server_info_label.pack(pady=5)

            # Instructions for Cloudflared/ngrok
            pub_button = ttk.Button(main_frame, text="Make Public (with ngrok/cloudflared)", command=self.show_public_info)
            pub_button.pack(pady=5)

            stop_button = ttk.Button(main_frame, text="Stop Collaboration", command=self.stop_collaboration)
            stop_button.pack(pady=10)

        # Chat frame
        chat_frame = ttk.LabelFrame(main_frame, text="Chat", padding="10")
        chat_frame.pack(expand=True, fill="both", pady=10)

        self.chat_text = tk.Text(chat_frame, wrap="word", state=tk.DISABLED, height=10, bg="#ffffff")
        self.chat_text.pack(expand=True, fill="both")

        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill="x", pady=(5, 0))

        self.chat_input = ttk.Entry(input_frame, width=50)
        self.chat_input.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.chat_input.bind("<Return>", self.send_chat_message)

        send_button = ttk.Button(input_frame, text="Send", command=self.send_chat_message)
        send_button.pack(side="right")

        # Start the thread to periodically sync the chat
        self.sync_thread = threading.Thread(target=self.sync_chat_periodically)
        self.sync_thread.daemon = True
        self.sync_thread.start()

    def sync_chat_periodically(self):
        """
        Synchronizes the chat every 2 seconds.
        """
        while not self.stop_server_event.is_set():
            self.sync_chat()
            time.sleep(2)

    def stop_collaboration(self):
        """
        Stops the collaboration (for the owner only).
        """
        if self.is_owner:
            try:
                requests.post("http://127.0.0.1:5000/stop")
            except requests.exceptions.RequestException:
                pass # The server might already be shut down

        self.stop_server_event.set()
        messagebox.showinfo("Collaboration Stopped", "The collaboration has been stopped.")
        self.back_to_main()

    def show_public_info(self):
        """
        Shows instructions for using ngrok or cloudflared.
        """
        info = (
            "To make your collaboration public so others can join, "
            "you need to use a tool like ngrok or cloudflared.\n\n"
            "1. Install ngrok or cloudflared.\n"
            "2. Open a terminal and run the command:\n"
            "   ngrok http 5000\n"
            "   or\n"
            "   cloudflared tunnel --url http://127.0.0.1:5000\n\n"
            "3. ngrok or cloudflared will give you a public URL that you can share with your collaborators. "
            "They will use that URL to join the collaboration."
        )
        messagebox.showinfo("Make Collaboration Public", info)

    def clear_frame(self, frame):
        """
        Clears all widgets from a frame.
        """
        for widget in frame.winfo_children():
            widget.destroy()

    def back_to_main(self):
        """
        Returns to the main screen and restarts the application.
        """
        self.stop_server_event.set()
        if self.server_thread and self.server_thread.is_alive():
            try:
                requests.post("http://127.0.0.1:5000/stop")
            except requests.exceptions.RequestException:
                pass
        self.destroy()
        CollabCX().mainloop()

if __name__ == "__main__":
    app = CollabCX()
    app.mainloop()
