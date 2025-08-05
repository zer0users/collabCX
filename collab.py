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
import hashlib
import base64
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# IMPORTANT: You need to install Flask and watchdog for this program to work.
# Open your terminal and run: pip install Flask watchdog


class FileWatcher(FileSystemEventHandler):
    """
    Observa cambios en el sistema de archivos y los reporta al servidor.
    Ahora con colaboración real para todos los usuarios.
    """

    def __init__(self, collab_instance):
        self.collab = collab_instance
        self.ignore_events = set()
        self.processing_files = set()  # Para evitar loops de sincronización

    def on_any_event(self, event):
        # Ignorar archivos temporales y ocultos
        if os.path.basename(event.src_path).startswith('.'):
            return

        if event.is_directory:
            if event.event_type == 'created':
                self.on_directory_created(event)
            elif event.event_type == 'deleted':
                self.on_directory_deleted(event)
            elif event.event_type == 'moved':
                self.on_directory_moved(event)
        else:
            # Manejar archivos
            if event.event_type in ['created', 'modified']:
                self.on_file_modified(event)
            elif event.event_type == 'deleted':
                self.on_file_deleted(event)
            elif event.event_type == 'moved':
                self.on_file_moved(event)

    def on_directory_created(self, event):
        """Maneja la creación de directorios."""
        rel_path = os.path.relpath(event.src_path, self.collab.collaboration_path)
        if rel_path.startswith('.') or rel_path in self.processing_files:
            return

        print(f"Directory created: {rel_path}")

        # TODOS pueden crear directorios
        if not self.collab.is_owner:
            self.collab.upload_directory(rel_path)
        else:
            # El owner actualiza su estado interno
            print(f"Owner directory created: {rel_path}")

    def on_file_modified(self, event):
        """Maneja la modificación de archivos."""
        rel_path = os.path.relpath(event.src_path, self.collab.collaboration_path)
        if rel_path.startswith('.') or rel_path in self.processing_files:
            return

        print(f"File modified: {rel_path}")

        # Verificar que realmente cambió el contenido
        current_hash = self.collab.get_file_hash(event.src_path)
        if current_hash and current_hash != self.collab.file_hashes.get(rel_path):
            print(f"File content changed: {rel_path} (hash: {current_hash})")
            self.collab.file_hashes[rel_path] = current_hash

            # TODOS pueden modificar archivos
            if not self.collab.is_owner:
                # Esperar un poco para asegurar que el archivo se haya terminado de escribir
                time.sleep(0.5)
                self.collab.upload_file(rel_path)
            else:
                # El owner también actualiza para propagar cambios
                print(f"Owner file updated: {rel_path}")

        else:
            print(f"File content unchanged: {rel_path}")

    def on_file_deleted(self, event):
        """Maneja la eliminación de archivos."""
        rel_path = os.path.relpath(event.src_path, self.collab.collaboration_path)
        if rel_path.startswith('.') or rel_path in self.processing_files:
            return

        print(f"File deleted: {rel_path}")

        # TODOS pueden eliminar archivos
        if not self.collab.is_owner:
            self.collab.delete_file(rel_path)
        else:
            print(f"Owner deleted file: {rel_path}")
            # Limpiar hash
            if rel_path in self.collab.file_hashes:
                del self.collab.file_hashes[rel_path]

    def on_directory_deleted(self, event):
        """Maneja la eliminación de directorios."""
        rel_path = os.path.relpath(event.src_path, self.collab.collaboration_path)
        if rel_path.startswith('.') or rel_path in self.processing_files:
            return

        print(f"Directory deleted: {rel_path}")

        # TODOS pueden eliminar directorios
        if not self.collab.is_owner:
            self.collab.delete_file(rel_path)
        else:
            print(f"Owner deleted directory: {rel_path}")

    def on_file_moved(self, event):
        """Maneja el movimiento/renombrado de archivos."""
        if hasattr(event, 'src_path') and hasattr(event, 'dest_path'):
            src_rel = os.path.relpath(event.src_path, self.collab.collaboration_path)
            dest_rel = os.path.relpath(event.dest_path, self.collab.collaboration_path)

            if src_rel.startswith('.') or dest_rel.startswith('.'):
                return

            print(f"File moved: {src_rel} -> {dest_rel}")

            # TODOS pueden mover/renombrar archivos
            if not self.collab.is_owner:
                # Primero eliminar el archivo original
                self.collab.delete_file(src_rel)
                # Luego subir el archivo en la nueva ubicación
                time.sleep(0.5)
                self.collab.upload_file(dest_rel)
            else:
                # El owner actualiza sus hashes
                if src_rel in self.collab.file_hashes:
                    hash_value = self.collab.file_hashes[src_rel]
                    del self.collab.file_hashes[src_rel]
                    self.collab.file_hashes[dest_rel] = hash_value
                print(f"Owner moved file: {src_rel} -> {dest_rel}")

    def on_directory_moved(self, event):
        """Maneja el movimiento/renombrado de directorios."""
        if hasattr(event, 'src_path') and hasattr(event, 'dest_path'):
            src_rel = os.path.relpath(event.src_path, self.collab.collaboration_path)
            dest_rel = os.path.relpath(event.dest_path, self.collab.collaboration_path)

            if src_rel.startswith('.') or dest_rel.startswith('.'):
                return

            print(f"Directory moved: {src_rel} -> {dest_rel}")

            # TODOS pueden mover/renombrar directorios
            if not self.collab.is_owner:
                # Eliminar directorio original
                self.collab.delete_file(src_rel)
                # Crear directorio en nueva ubicación
                self.collab.upload_directory(dest_rel)
                # Subir todos los archivos que estaban en el directorio
                self.collab.upload_directory_contents(dest_rel)
            else:
                print(f"Owner moved directory: {src_rel} -> {dest_rel}")


class CollabCX(tk.Tk):
    """
    CollabCX es una aplicación de colaboración de archivos y chat en tiempo real.
    Permite a los usuarios crear una nueva colaboración o unirse a una existente.
    Ahora con sincronización bidireccional completa y colaboración real.
    """

    def __init__(self):
        super().__init__()
        self.title("CollabCX - Collaborate with Love (Enhanced & Fixed)")
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
        self.lock = threading.Lock()
        self.file_hashes = {}  # Para rastrear cambios en archivos
        self.observer = None   # Para watchdog
        self.server_url = ""
        self.sync_in_progress = False  # Para evitar loops

        self.create_widgets()

    def create_widgets(self):
        """
        Crea la interfaz de usuario para la aplicación.
        """
        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        style = ttk.Style()
        style.configure("TFrame", background="#f0f2f5")
        style.configure("TButton", font=("Helvetica", 12), padding=10)
        style.configure("TLabel", background="#f0f2f5", font=("Helvetica", 14))

        title_label = ttk.Label(
            main_frame, text="Welcome to CollabCX Enhanced & Fixed", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)

        desc_label = ttk.Label(
            main_frame, text="Colabora con sincronización bidireccional completa. ¡Ahora TODOS pueden editar!", font=("Helvetica", 16))
        desc_label.pack(pady=10)

        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=20)

        create_button = ttk.Button(
            button_frame, text="Create Collaboration", command=self.create_collaboration_view)
        create_button.pack(side="left", padx=10)

        join_button = ttk.Button(
            button_frame, text="Join Collaboration", command=self.join_collaboration_view)
        join_button.pack(side="left", padx=10)

    def create_collaboration_view(self):
        """
        Muestra la interfaz para crear una colaboración.
        """
        self.clear_frame(self)
        self.is_owner = True

        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        title_label = ttk.Label(
            main_frame, text="Create a New Collaboration", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)

        path_label = ttk.Label(main_frame, text="Select the project folder:")
        path_label.pack(pady=(10, 5))

        self.path_entry = ttk.Entry(main_frame, width=50)
        self.path_entry.pack(pady=5)

        browse_button = ttk.Button(
            main_frame, text="Browse Folder", command=self.select_folder)
        browse_button.pack(pady=5)

        start_button = ttk.Button(
            main_frame, text="Start Collaboration", command=self.start_collaboration)
        start_button.pack(pady=20)

        back_button = ttk.Button(
            main_frame, text="Back", command=self.back_to_main)
        back_button.pack(pady=5)

    def join_collaboration_view(self):
        """
        Muestra la interfaz para unirse a una colaboración.
        """
        self.clear_frame(self)
        self.is_owner = False

        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        title_label = ttk.Label(
            main_frame, text="Join a Collaboration", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)

        server_label = ttk.Label(
            main_frame, text="Enter the server address (URL):")
        server_label.pack(pady=(10, 5))

        self.server_entry = ttk.Entry(main_frame, width=50)
        self.server_entry.pack(pady=5)

        join_button = ttk.Button(
            main_frame, text="Join", command=self.join_collaboration)
        join_button.pack(pady=20)

        back_button = ttk.Button(
            main_frame, text="Back", command=self.back_to_main)
        back_button.pack(pady=5)

    def select_folder(self):
        """
        Abre un diálogo para que el usuario seleccione una carpeta.
        """
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder_path)

    def get_file_hash(self, filepath):
        """
        Calcula el hash MD5 de un archivo.
        """
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None

    def scan_files(self):
        """
        Escanea todos los archivos y carpetas en el directorio de colaboración.
        """
        files_info = {}
        directories = set()

        for root, dirs, files in os.walk(self.collaboration_path):
            # Agregar directorios
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                rel_dir = os.path.relpath(dir_path, self.collaboration_path)
                if not rel_dir.startswith('.'):
                    directories.add(rel_dir)

            # Agregar archivos
            for file_name in files:
                file_path = os.path.join(root, file_name)
                rel_file = os.path.relpath(file_path, self.collaboration_path)
                if not rel_file.startswith('.'):
                    file_hash = self.get_file_hash(file_path)
                    file_stat = os.stat(file_path)
                    files_info[rel_file] = {
                        'hash': file_hash,
                        'size': file_stat.st_size,
                        'mtime': file_stat.st_mtime
                    }

        return files_info, directories

    def start_collaboration(self):
        """
        Inicia la colaboración como propietario.
        """
        self.collaboration_path = self.path_entry.get()
        if not os.path.isdir(self.collaboration_path):
            messagebox.showerror("Error", "The folder path is not valid.")
            return

        self.collaboration_name = os.path.basename(self.collaboration_path)
        self.stop_server_event.clear()

        # Escanear archivos iniciales
        self.file_hashes, _ = self.scan_files()

        # Iniciar el servidor Flask en un hilo separado
        self.server_thread = threading.Thread(target=self.run_flask_server)
        self.server_thread.daemon = True
        self.server_thread.start()

        # Iniciar el observador de archivos
        self.start_file_watcher()

        self.open_collaboration_window()

    def start_file_watcher(self):
        """
        Inicia el observador de cambios en archivos.
        """
        if self.observer:
            self.observer.stop()
            self.observer.join()

        self.observer = Observer()
        event_handler = FileWatcher(self)
        self.observer.schedule(
            event_handler, self.collaboration_path, recursive=True)
        self.observer.start()

    def join_collaboration(self):
        """
        Se une a una colaboración existente.
        """
        server_url = self.server_entry.get()
        if not server_url:
            messagebox.showerror("Error", "Please enter a server URL.")
            return

        # Verificar si es una colaboración CollabCX
        try:
            response = requests.get(f"{server_url}/verify")
            if response.status_code == 200 and response.json().get("status") == "CollabCX":
                collaboration_name = response.json().get("name")
                self.collaboration_name = collaboration_name
                self.collaboration_path = os.path.join(
                    os.getcwd(), collaboration_name)

                # Crear la carpeta si no existe y descargar los archivos
                if not os.path.exists(self.collaboration_path):
                    os.makedirs(self.collaboration_path)

                self.server_url = server_url

                # Sincronización inicial
                self.initial_sync()

                # Iniciar el observador de archivos
                self.start_file_watcher()

                # Iniciar hilo de sincronización
                self.sync_thread = threading.Thread(
                    target=self.sync_client_files)
                self.sync_thread.daemon = True
                self.sync_thread.start()

                self.open_collaboration_window()
            else:
                messagebox.showerror(
                    "Error", "This is not a valid CollabCX server.")
        except requests.exceptions.RequestException:
            messagebox.showerror(
                "Error", "Could not connect to the server. Check the URL.")

    def initial_sync(self):
        """
        Realiza la sincronización inicial al unirse a una colaboración.
        """
        try:
            self.sync_in_progress = True
            # Obtener estructura del servidor
            response = requests.get(f"{self.server_url}/get_structure")
            if response.status_code == 200:
                server_structure = response.json()

                # Crear directorios
                for directory in server_structure.get('directories', []):
                    dir_path = os.path.join(self.collaboration_path, directory)
                    os.makedirs(dir_path, exist_ok=True)

                # Descargar archivos
                for filename, file_info in server_structure.get('files', {}).items():
                    self.download_file(filename)

            self.sync_in_progress = False

        except requests.exceptions.RequestException:
            self.sync_in_progress = False
            messagebox.showerror("Error", "Failed to perform initial sync.")

    def upload_file(self, filename):
        """
        Sube un archivo al servidor.
        """
        if self.sync_in_progress:
            return

        try:
            full_path = os.path.join(self.collaboration_path, filename)
            if os.path.exists(full_path):
                with open(full_path, 'rb') as f:
                    files = {'file': f}
                    data = {'filename': filename}
                    response = requests.post(
                        f"{self.server_url}/upload_file", files=files, data=data)
                    print(f"Upload response for {filename}: {response.status_code}")
        except Exception as e:
            print(f"Error uploading {filename}: {e}")

    def upload_directory(self, dirname):
        """
        Crea un directorio en el servidor.
        """
        if self.sync_in_progress:
            return

        try:
            data = {'dirname': dirname}
            response = requests.post(
                f"{self.server_url}/create_directory", data=data)
            print(f"Directory creation response for {dirname}: {response.status_code}")
        except Exception as e:
            print(f"Error creating directory {dirname}: {e}")

    def upload_directory_contents(self, dirname):
        """
        Sube todos los archivos de un directorio (útil para mover directorios).
        """
        if self.sync_in_progress:
            return

        dir_path = os.path.join(self.collaboration_path, dirname)
        if os.path.exists(dir_path):
            for root, dirs, files in os.walk(dir_path):
                # Crear subdirectorios
                for subdir in dirs:
                    subdir_path = os.path.join(root, subdir)
                    rel_subdir = os.path.relpath(subdir_path, self.collaboration_path)
                    self.upload_directory(rel_subdir)

                # Subir archivos
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_file = os.path.relpath(file_path, self.collaboration_path)
                    self.upload_file(rel_file)

    def delete_file(self, filename):
        """
        Elimina un archivo del servidor.
        """
        if self.sync_in_progress:
            return

        try:
            data = {'filename': filename}
            response = requests.post(
                f"{self.server_url}/delete_file", data=data)
            print(f"Delete response for {filename}: {response.status_code}")
        except Exception as e:
            print(f"Error deleting {filename}: {e}")

    def run_flask_server(self):
        """
        Configura y ejecuta el servidor Flask.
        """
        self.app = Flask(__name__)

        @self.app.route("/verify")
        def verify():
            return jsonify({"status": "CollabCX", "name": self.collaboration_name})

        @self.app.route("/<path:filename>")
        def get_file(filename):
            try:
                return send_from_directory(self.collaboration_path, filename)
            except:
                abort(404)

        @self.app.route("/get_structure")
        def get_structure():
            files_info, directories = self.scan_files()
            return jsonify({
                'files': files_info,
                'directories': list(directories)
            })

        @self.app.route("/upload_file", methods=["POST"])
        def upload_file():
            try:
                file = request.files['file']
                filename = request.form['filename']

                full_path = os.path.join(self.collaboration_path, filename)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)

                # Marcar como en sincronización para evitar loops
                self.sync_in_progress = True
                file.save(full_path)
                self.sync_in_progress = False

                # Actualizar hash del archivo
                file_hash = self.get_file_hash(full_path)
                self.file_hashes[filename] = file_hash

                print(f"File received with love ❤️: {full_path} (hash: {file_hash})")
                return "OK"
            except Exception as e:
                self.sync_in_progress = False
                print(f"Error in upload_file: {e}")
                return "Error", 500

        @self.app.route("/create_directory", methods=["POST"])
        def create_directory():
            try:
                dirname = request.form['dirname']
                full_path = os.path.join(self.collaboration_path, dirname)

                self.sync_in_progress = True
                os.makedirs(full_path, exist_ok=True)
                self.sync_in_progress = False

                print(f"Directory created: {full_path}")
                return "OK"
            except Exception as e:
                self.sync_in_progress = False
                print(f"Error in create_directory: {e}")
                return "Error", 500

        @self.app.route("/delete_file", methods=["POST"])
        def delete_file():
            try:
                filename = request.form['filename']
                full_path = os.path.join(self.collaboration_path, filename)

                if os.path.exists(full_path):
                    self.sync_in_progress = True

                    if os.path.isfile(full_path):
                        os.remove(full_path)
                        print(f"File deleted: {full_path}")
                    elif os.path.isdir(full_path):
                        # Eliminar directorio y todo su contenido
                        shutil.rmtree(full_path)
                        print(f"Directory deleted: {full_path}")

                        # También actualizar la lista de file_hashes para remover archivos de esta carpeta
                        keys_to_remove = [key for key in self.file_hashes.keys(
                        ) if key.startswith(filename + os.sep) or key == filename]
                        for key in keys_to_remove:
                            del self.file_hashes[key]

                    self.sync_in_progress = False

                return "OK"
            except Exception as e:
                self.sync_in_progress = False
                print(f"Error in delete_file: {e}")
                return "Error", 500

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
            self.app.run(port=5000, threaded=True)
        except Exception as e:
            messagebox.showerror(
                "Server Error", f"Error starting the server: {e}")
            self.stop_server_event.set()

    def sync_client_files(self):
        """
        Sincroniza los archivos del cliente con el servidor.
        """
        while not self.stop_server_event.is_set():
            try:
                if self.sync_in_progress:
                    time.sleep(2)
                    continue

                response = requests.get(f"{self.server_url}/get_structure")
                if response.status_code == 200:
                    server_structure = response.json()
                    server_files = set(
                        server_structure.get('files', {}).keys())
                    server_dirs = set(server_structure.get('directories', []))

                    # Obtener archivos y directorios locales
                    local_files_info, local_dirs = self.scan_files()
                    local_files = set(local_files_info.keys())

                    self.sync_in_progress = True

                    # Crear directorios que existen en el servidor pero no localmente
                    for directory in server_dirs - local_dirs:
                        dir_path = os.path.join(
                            self.collaboration_path, directory)
                        os.makedirs(dir_path, exist_ok=True)
                        print(f"Created directory: {directory}")

                    # Eliminar directorios que ya no existen en el servidor
                    for directory in local_dirs - server_dirs:
                        dir_path = os.path.join(
                            self.collaboration_path, directory)
                        if os.path.exists(dir_path):
                            shutil.rmtree(dir_path)
                            print(f"Removed directory: {directory}")

                    # Descargar archivos nuevos o actualizados
                    for filename in server_files:
                        if filename not in local_files:
                            print(f"Downloading new file: {filename}")
                            self.download_file(filename)
                        else:
                            # Verificar si ha cambiado comparando hashes
                            server_info = server_structure['files'][filename]
                            local_info = local_files_info.get(filename, {})
                            if server_info.get('hash') != local_info.get('hash'):
                                print(
                                    f"File changed on server, updating with love ❤️: {filename}")
                                self.download_file(filename)
                                # Actualizar hash local
                                full_path = os.path.join(
                                    self.collaboration_path, filename)
                                self.file_hashes[filename] = self.get_file_hash(
                                    full_path)

                    # Eliminar archivos que ya no existen en el servidor
                    for filename in local_files - server_files:
                        full_path = os.path.join(
                            self.collaboration_path, filename)
                        if os.path.exists(full_path):
                            os.remove(full_path)
                            print(f"Removed file: {filename}")
                            # Limpiar hash
                            if filename in self.file_hashes:
                                del self.file_hashes[filename]

                    self.sync_in_progress = False

                # Sincronizar chat
                self.sync_chat()

            except requests.exceptions.RequestException:
                self.sync_in_progress = False
                if not self.is_owner:
                    messagebox.showinfo(
                        "Collaboration Ended", "The owner has stopped the collaboration.")
                    self.stop_server_event.set()
                    self.back_to_main()
                    break

            time.sleep(2)

    def download_file(self, filename):
        """
        Descarga un archivo del servidor con amor ❤️.
        """
        try:
            response = requests.get(f"{self.server_url}/{filename}")
            if response.status_code == 200:
                full_path = os.path.join(self.collaboration_path, filename)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "wb") as f:
                    f.write(response.content)

                # Actualizar hash local
                file_hash = self.get_file_hash(full_path)
                self.file_hashes[filename] = file_hash

                print(f"Downloaded with love ❤️: {filename} (hash: {file_hash})")
        except Exception as e:
            print(f"Error downloading {filename}: {e}")

    def sync_chat(self):
        """
        Sincroniza el historial de chat con el servidor.
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
        Envía un nuevo mensaje al chat.
        """
        message = self.chat_input.get()
        if not message:
            return

        if self.is_owner:
            with self.lock:
                self.chat_history.append(f"Owner: {message}")
        else:
            try:
                requests.post(f"{self.server_url}/chat",
                              json={"message": f"Collaborator: {message}"})
            except requests.exceptions.RequestException:
                messagebox.showerror(
                    "Error", "Could not send the message. The server is not responding.")

        self.chat_input.delete(0, tk.END)
        self.sync_chat()

    def update_chat_display(self, messages):
        """
        Actualiza el widget de texto del chat con nuevos mensajes.
        """
        if hasattr(self, 'chat_text'):
            self.chat_text.config(state=tk.NORMAL)
            self.chat_text.delete(1.0, tk.END)
            for msg in messages:
                self.chat_text.insert(tk.END, msg + "\n")
            self.chat_text.config(state=tk.DISABLED)
            self.chat_text.see(tk.END)

    def open_collaboration_window(self):
        """
        Abre la ventana de colaboración con chat y detalles.
        """
        self.clear_frame(self)

        main_frame = ttk.Frame(self, padding="20", style="TFrame")
        main_frame.pack(expand=True, fill="both")

        title_text = f"Collaboration: {self.collaboration_name}"
        title_label = ttk.Label(
            main_frame, text=title_text, font=("Helvetica", 24, "bold"))
        title_label.pack(pady=10)

        # Mostrar rol del usuario
        role_text = "Owner (Dueño)" if self.is_owner else "Collaborator (Colaborador)"
        role_label = ttk.Label(
            main_frame, text=f"Your role: {role_text}", font=("Helvetica", 12, "italic"))
        role_label.pack(pady=5)

        # Mensaje de mejora
        improvement_label = ttk.Label(
            main_frame, text="¡Ahora TODOS pueden editar, crear, mover y renombrar archivos!",
            font=("Helvetica", 14, "bold"), foreground="green")
        improvement_label.pack(pady=5)

        # Si el usuario es el propietario, mostrar información del servidor
        if self.is_owner:
            ip_addr = "127.0.0.1:5000"
            server_info_label = ttk.Label(
                main_frame, text=f"Server started at: http://{ip_addr}", font=("Helvetica", 12))
            server_info_label.pack(pady=5)

            # Instrucciones para Cloudflared/ngrok
            pub_button = ttk.Button(
                main_frame, text="Make Public (with ngrok/cloudflared)", command=self.show_public_info)
            pub_button.pack(pady=5)

            stop_button = ttk.Button(
                main_frame, text="Stop Collaboration", command=self.stop_collaboration)
            stop_button.pack(pady=10)

        # Marco del chat
        chat_frame = ttk.LabelFrame(main_frame, text="Chat", padding="10")
        chat_frame.pack(expand=True, fill="both", pady=10)

        self.chat_text = tk.Text(
            chat_frame, wrap="word", state=tk.DISABLED, height=10, bg="#ffffff")
        self.chat_text.pack(expand=True, fill="both")

        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill="x", pady=(5, 0))

        self.chat_input = ttk.Entry(input_frame, width=50)
        self.chat_input.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.chat_input.bind("<Return>", self.send_chat_message)

        send_button = ttk.Button(
            input_frame, text="Send", command=self.send_chat_message)
        send_button.pack(side="right")

        # Marco de información de archivos
        info_frame = ttk.LabelFrame(main_frame, text="Collaboration Info", padding="10")
        info_frame.pack(fill="x", pady=5)

        path_info = ttk.Label(
            info_frame, text=f"Project Path: {self.collaboration_path}", font=("Helvetica", 10))
        path_info.pack(anchor="w")

        # Iniciar el hilo para sincronizar el chat periódicamente
        self.sync_thread = threading.Thread(target=self.sync_chat_periodically)
        self.sync_thread.daemon = True
        self.sync_thread.start()

    def sync_chat_periodically(self):
        """
        Sincroniza el chat cada 2 segundos.
        """
        while not self.stop_server_event.is_set():
            self.sync_chat()
            time.sleep(2)

    def stop_collaboration(self):
        """
        Detiene la colaboración (solo para el propietario).
        """
        if self.observer:
            self.observer.stop()
            self.observer.join()

        if self.is_owner:
            try:
                requests.post("http://127.0.0.1:5000/stop")
            except requests.exceptions.RequestException:
                pass

        self.stop_server_event.set()
        messagebox.showinfo("Collaboration Stopped",
                            "The collaboration has been stopped.")
        self.back_to_main()

    def show_public_info(self):
        """
        Muestra instrucciones para usar ngrok o cloudflared.
        """
        info = (
            "Para hacer tu colaboración pública y que otros puedan unirse, "
            "necesitas usar una herramienta como ngrok o cloudflared.\n\n"
            "1. Instala ngrok o cloudflared.\n"
            "2. Abre una terminal y ejecuta el comando:\n"
            "   ngrok http 5000\n"
            "   o\n"
            "   cloudflared tunnel --url http://127.0.0.1:5000\n\n"
            "3. ngrok o cloudflared te dará una URL pública que puedes compartir con tus colaboradores. "
            "Ellos usarán esa URL para unirse a la colaboración.\n\n"
            "¡Ahora todos podrán colaborar editando archivos en tiempo real!"
        )
        messagebox.showinfo("Make Collaboration Public", info)

    def clear_frame(self, frame):
        """
        Limpia todos los widgets de un frame.
        """
        for widget in frame.winfo_children():
            widget.destroy()

    def back_to_main(self):
        """
        Regresa a la pantalla principal y reinicia la aplicación.
        """
        if self.observer:
            self.observer.stop()
            self.observer.join()

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
