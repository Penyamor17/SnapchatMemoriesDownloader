import customtkinter as ctk
from tkinter import filedialog, messagebox

import html
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile

from datetime import datetime
from pathlib import Path


# ============================================================
# KONFIGURATION
# ============================================================

APP_TITLE = "Snapchat Memories Downloader"
APP_VERSION = "1.0"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/120 Safari/537.36"
)

CHUNK_SIZE = 1024 * 1024
TIMEOUT = 60


# ============================================================
# CUSTOMTKINTER
# ============================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ============================================================
# HILFSFUNKTIONEN
# ============================================================

def extract_url(value):
    """
    Extrahiert die eigentliche Download-URL.

    Unterstützt:
    - direkte URLs
    - HTML ......</a>
    """

    if not isinstance(value, str):
        return None

    value = html.unescape(value.strip())

    # URL aus href="..." extrahieren
    match = re.search(
        r'href\s*=\s*[^"\']+["\']',
        value,
        re.IGNORECASE
    )

    if match:
        return html.unescape(match.group(1))

    # Falls direkt eine URL gespeichert wurde
    match = re.search(
        r'https?://[^\s<"\']+',
        value
    )

    if match:
        return match.group(0)

    return None


def safe_date(value):
    """
    Wandelt das Snapchat-Datum in einen sicheren Dateinamen um.
    """

    formats = (
        "%Y-%m-%d %H:%M:%S UTC",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    )

    for date_format in formats:
        try:
            parsed = datetime.strptime(
                str(value),
                date_format
            )

            return parsed.strftime(
                "%Y-%m-%d_%H-%M-%S"
            )

        except ValueError:
            pass

    # Fallback
    cleaned = re.sub(
        r"[^0-9A-Za-z_-]+",
        "_",
        str(value or "unknown_date")
    )

    cleaned = cleaned.strip("_")

    if not cleaned:
        cleaned = "unknown_date"

    return cleaned[:60]


def extension_from_response(
    content_type,
    final_url,
    media_type
):
    """
    Bestimmt die Dateiendung anhand des Content-Type,
    der URL oder des Media Type.
    """

    content_type = (
        (content_type or "")
        .split(";", 1)[0]
        .lower()
        .strip()
    )

    known_types = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "image/gif": ".gif",
    }

    # --------------------------------------------------------
    # Content-Type
    # --------------------------------------------------------

    if content_type in known_types:
        return known_types[content_type]

    # --------------------------------------------------------
    # MIME-Type automatisch bestimmen
    # --------------------------------------------------------

    if content_type:
        guessed_extension = mimetypes.guess_extension(
            content_type
        )

        if guessed_extension:
            if guessed_extension == ".jpe":
                return ".jpg"

            return guessed_extension

    # --------------------------------------------------------
    # Dateiendung aus URL
    # --------------------------------------------------------

    try:
        parsed_url = urllib.parse.urlparse(
            final_url
        )

        url_extension = Path(
            parsed_url.path
        ).suffix.lower()

        if url_extension and len(url_extension) <= 6:
            return url_extension

    except Exception:
        pass

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    media_type = str(
        media_type
    ).upper()

    if media_type == "VIDEO":
        return ".mp4"

    if media_type == "PHOTO":
        return ".jpg"

    return ".bin"


def is_invalid_content_type(content_type):
    """
    Erkennt offensichtliche Fehlerantworten.

    Damit wird beispielsweise verhindert, dass eine HTML-Seite
    versehentlich als MP4 gespeichert wird.
    """

    content_type = (
        content_type or ""
    ).lower()

    invalid_types = (
        "text/html",
        "text/plain",
        "application/json",
        "application/xml",
    )

    return any(
        invalid_type in content_type
        for invalid_type in invalid_types
    )


# ============================================================
# HAUPTANWENDUNG
# ============================================================

class SnapchatDownloaderApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        # ----------------------------------------------------
        # Fenster
        # ----------------------------------------------------

        self.title(
            f"{APP_TITLE} v{APP_VERSION}"
        )

        self.geometry(
            "900x760"
        )

        self.minsize(
            780,
            680
        )

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        self.json_path = ""
        self.output_dir = ""

        self.running = False

        self.cancel_event = threading.Event()

        # ----------------------------------------------------
        # Tkinter-Variablen
        # ----------------------------------------------------

        self.mode_var = ctk.StringVar(
            value="files"
        )

        self.skip_existing_var = ctk.BooleanVar(
            value=True
        )

        self.json_label_var = ctk.StringVar(
            value="Keine JSON-Datei ausgewählt"
        )

        self.folder_label_var = ctk.StringVar(
            value="Kein Zielordner ausgewählt"
        )

        self.status_var = ctk.StringVar(
            value="Bereit"
        )

        self.count_var = ctk.StringVar(
            value="0 / 0"
        )

        # ----------------------------------------------------
        # Grid
        # ----------------------------------------------------

        self.grid_columnconfigure(
            0,
            weight=1
        )

        self.grid_rowconfigure(
            4,
            weight=1
        )

        # ----------------------------------------------------
        # UI
        # ----------------------------------------------------

        self.build_ui()

        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )

    # ========================================================
    # OBERFLÄCHE
    # ========================================================

    def build_ui(self):

        # ====================================================
        # HEADER
        # ====================================================

        header = ctk.CTkFrame(
            self,
            fg_color="transparent"
        )

        header.grid(
            row=0,
            column=0,
            padx=28,
            pady=(25, 12),
            sticky="ew"
        )

        title = ctk.CTkLabel(
            header,
            text="Snapchat Memories Downloader",
            font=ctk.CTkFont(
                size=28,
                weight="bold"
            )
        )

        title.pack(
            anchor="w"
        )

        subtitle = ctk.CTkLabel(
            header,
            text=(
                "Snapchat-Export auswählen, "
                "Ziel bestimmen und Memories herunterladen."
            ),
            text_color="gray70"
        )

        subtitle.pack(
            anchor="w",
            pady=(4, 0)
        )

        # ====================================================
        # JSON-AUSWAHL
        # ====================================================

        selection = ctk.CTkFrame(
            self,
            corner_radius=14
        )

        selection.grid(
            row=1,
            column=0,
            padx=28,
            pady=8,
            sticky="ew"
        )

        selection.grid_columnconfigure(
            0,
            weight=1
        )

        selection_title = ctk.CTkLabel(
            selection,
            text="1. Snapchat JSON",
            font=ctk.CTkFont(
                size=16,
                weight="bold"
            )
        )

        selection_title.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=18,
            pady=(16, 8),
            sticky="w"
        )

        json_label = ctk.CTkLabel(
            selection,
            textvariable=self.json_label_var,
            anchor="w"
        )

        json_label.grid(
            row=1,
            column=0,
            padx=(18, 10),
            pady=(0, 16),
            sticky="ew"
        )

        json_button = ctk.CTkButton(
            selection,
            text="JSON auswählen",
            command=self.choose_json,
            width=150
        )

        json_button.grid(
            row=1,
            column=1,
            padx=(10, 18),
            pady=(0, 16)
        )

        # ====================================================
        # ZIELORDNER
        # ====================================================

        destination = ctk.CTkFrame(
            self,
            corner_radius=14
        )

        destination.grid(
            row=2,
            column=0,
            padx=28,
            pady=8,
            sticky="ew"
        )

        destination.grid_columnconfigure(
            0,
            weight=1
        )

        destination_title = ctk.CTkLabel(
            destination,
            text="2. Ablageort und Ausgabe",
            font=ctk.CTkFont(
                size=16,
                weight="bold"
            )
        )

        destination_title.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=18,
            pady=(16, 8),
            sticky="w"
        )

        folder_label = ctk.CTkLabel(
            destination,
            textvariable=self.folder_label_var,
            anchor="w"
        )

        folder_label.grid(
            row=1,
            column=0,
            padx=(18, 10),
            pady=8,
            sticky="ew"
        )

        folder_button = ctk.CTkButton(
            destination,
            text="Ordner auswählen",
            command=self.choose_folder,
            width=150
        )

        folder_button.grid(
            row=1,
            column=1,
            padx=(10, 18),
            pady=8
        )

        # ----------------------------------------------------
        # Optionen
        # ----------------------------------------------------

        options = ctk.CTkFrame(
            destination,
            fg_color="transparent"
        )

        options.grid(
            row=2,
            column=0,
            columnspan=2,
            padx=18,
            pady=(4, 16),
            sticky="w"
        )

        files_radio = ctk.CTkRadioButton(
            options,
            text="Einzelne Dateien direkt im Ordner speichern",
            variable=self.mode_var,
            value="files"
        )

        files_radio.pack(
            anchor="w",
            pady=4
        )

        zip_radio = ctk.CTkRadioButton(
            options,
            text="Als ZIP-Datei ablegen",
            variable=self.mode_var,
            value="zip"
        )

        zip_radio.pack(
            anchor="w",
            pady=4
        )

        skip_checkbox = ctk.CTkCheckBox(
            options,
            text="Bereits vorhandene Dateien überspringen",
            variable=self.skip_existing_var
        )

        skip_checkbox.pack(
            anchor="w",
            pady=(9, 3)
        )

        # ====================================================
        # BUTTONS
        # ====================================================

        actions = ctk.CTkFrame(
            self,
            fg_color="transparent"
        )

        actions.grid(
            row=3,
            column=0,
            padx=28,
            pady=(12, 5),
            sticky="ew"
        )

        actions.grid_columnconfigure(
            0,
            weight=1
        )

        self.start_button = ctk.CTkButton(
            actions,
            text="Download starten",
            height=44,
            command=self.start_download
        )

        self.start_button.grid(
            row=0,
            column=0,
            padx=(0, 8),
            sticky="ew"
        )

        self.cancel_button = ctk.CTkButton(
            actions,
            text="Abbrechen",
            height=44,
            width=130,
            fg_color="#8b2e2e",
            hover_color="#6e2424",
            command=self.cancel_download,
            state="disabled"
        )

        self.cancel_button.grid(
            row=0,
            column=1,
            padx=(8, 0)
        )

        # ====================================================
        # FORTSCHRITTSBEREICH
        # ====================================================

        progress_box = ctk.CTkFrame(
            self,
            corner_radius=14
        )

        progress_box.grid(
            row=4,
            column=0,
            padx=28,
            pady=(8, 25),
            sticky="nsew"
        )

        progress_box.grid_columnconfigure(
            0,
            weight=1
        )

        progress_box.grid_rowconfigure(
            4,
            weight=1
        )

        # ----------------------------------------------------
        # Status Header
        # ----------------------------------------------------

        status_header = ctk.CTkFrame(
            progress_box,
            fg_color="transparent"
        )

        status_header.grid(
            row=0,
            column=0,
            padx=18,
            pady=(15, 5),
            sticky="ew"
        )

        status_label = ctk.CTkLabel(
            status_header,
            textvariable=self.status_var,
            font=ctk.CTkFont(
                weight="bold"
            )
        )

        status_label.pack(
            side="left"
        )

        count_label = ctk.CTkLabel(
            status_header,
            textvariable=self.count_var,
            text_color="gray70"
        )

        count_label.pack(
            side="right"
        )

        # ----------------------------------------------------
        # Fortschrittsbalken
        # ----------------------------------------------------

        self.progress = ctk.CTkProgressBar(
            progress_box
        )

        self.progress.grid(
            row=1,
            column=0,
            padx=18,
            pady=8,
            sticky="ew"
        )

        self.progress.set(0)

        # ----------------------------------------------------
        # Detail-Anzeige
        # ----------------------------------------------------

        self.detail_label = ctk.CTkLabel(
            progress_box,
            text="Bereit für den Download.",
            anchor="w",
            text_color="gray70"
        )

        self.detail_label.grid(
            row=2,
            column=0,
            padx=18,
            pady=(0, 8),
            sticky="ew"
        )

        # ----------------------------------------------------
        # Protokoll-Titel
        # ----------------------------------------------------

        log_title = ctk.CTkLabel(
            progress_box,
            text="Protokoll",
            font=ctk.CTkFont(
                size=14,
                weight="bold"
            )
        )

        log_title.grid(
            row=3,
            column=0,
            padx=18,
            pady=(4, 4),
            sticky="w"
        )

        # ----------------------------------------------------
        # Protokoll
        # ----------------------------------------------------

        self.log_box = ctk.CTkTextbox(
            progress_box,
            height=170
        )

        self.log_box.grid(
            row=4,
            column=0,
            padx=18,
            pady=(0, 18),
            sticky="nsew"
        )

        self.log_box.configure(
            state="disabled"
        )

    # ========================================================
    # JSON AUSWÄHLEN
    # ========================================================

    def choose_json(self):

        path = filedialog.askopenfilename(
            title="Snapchat JSON auswählen",
            filetypes=[
                ("JSON-Dateien", "*.json"),
                ("Alle Dateien", "*.*"),
            ]
        )

        if not path:
            return

        self.json_path = path

        self.json_label_var.set(
            path
        )

        self.log(
            f"JSON ausgewählt: {path}"
        )

    # ========================================================
    # ZIELORDNER AUSWÄHLEN
    # ========================================================

    def choose_folder(self):

        path = filedialog.askdirectory(
            title="Ablageort auswählen"
        )

        if not path:
            return

        self.output_dir = path

        self.folder_label_var.set(
            path
        )

        self.log(
            f"Zielordner: {path}"
        )

    # ========================================================
    # DOWNLOAD STARTEN
    # ========================================================

    def start_download(self):

        if self.running:
            return

        # JSON prüfen
        if (
            not self.json_path
            or not os.path.isfile(self.json_path)
        ):
            messagebox.showwarning(
                APP_TITLE,
                "Bitte zuerst eine gültige Snapchat-JSON-Datei auswählen."
            )
            return

        # Zielordner prüfen
        if (
            not self.output_dir
            or not os.path.isdir(self.output_dir)
        ):
            messagebox.showwarning(
                APP_TITLE,
                "Bitte zuerst einen gültigen Ablageordner auswählen."
            )
            return

        self.cancel_event.clear()

        self.running = True

        self.start_button.configure(
            state="disabled"
        )

        self.cancel_button.configure(
            state="normal"
        )

        self.progress.set(0)

        self.status_var.set(
            "JSON wird gelesen ..."
        )

        self.count_var.set(
            "0 / 0"
        )

        self.detail_label.configure(
            text="Download wird vorbereitet ..."
        )

        self.clear_log()

        self.log(
            f"JSON: {self.json_path}"
        )

        self.log(
            f"Ziel: {self.output_dir}"
        )

        if self.mode_var.get() == "zip":
            self.log("Modus: ZIP-Datei")
        else:
            self.log("Modus: Einzeldateien")

        thread = threading.Thread(
            target=self.worker,
            daemon=True
        )

        thread.start()

    # ========================================================
    # ABBRECHEN
    # ========================================================

    def cancel_download(self):

        if not self.running:
            return

        self.cancel_event.set()

        self.status_var.set(
            "Abbruch wird ausgeführt ..."
        )

        self.cancel_button.configure(
            state="disabled"
        )

        self.log(
            "Abbruch angefordert ..."
        )

    # ========================================================
    # JSON LADEN
    # ========================================================

    def load_memories(self):

        with open(
            self.json_path,
            "r",
            encoding="utf-8-sig"
        ) as file:
            data = json.load(file)

        # ----------------------------------------------------
        # Direkt eine Liste
        # ----------------------------------------------------

        if isinstance(data, list):
            return data

        # ----------------------------------------------------
        # Liste innerhalb eines Objektes
        # ----------------------------------------------------

        if isinstance(data, dict):

            preferred_keys = (
                "Memories",
                "memories",
                "Saved Media",
                "saved_media",
            )

            for key in preferred_keys:

                value = data.get(key)

                if isinstance(value, list):
                    return value

            # Falls genau eine Liste innerhalb der JSON existiert
            lists = [
                value
                for value in data.values()
                if isinstance(value, list)
            ]

            if len(lists) == 1:
                return lists[0]

        raise ValueError(
            "In der JSON-Datei wurde keine eindeutige Memories-Liste gefunden."
        )

    # ========================================================
    # DOWNLOAD WORKER
    # ========================================================

    def worker(self):

        temp_dir = None

        try:

            memories = self.load_memories()

            total = len(memories)

            if total == 0:
                raise ValueError(
                    "Die JSON-Datei enthält keine Memories."
                )

            self.log(
                f"{total} Memories gefunden."
            )

            # ------------------------------------------------
            # Ausgabe-Modus
            # ------------------------------------------------

            zip_mode = (
                self.mode_var.get() == "zip"
            )

            if zip_mode:

                temp_dir = tempfile.mkdtemp(
                    prefix="snapchat_memories_"
                )

                download_dir = temp_dir

            else:

                download_dir = self.output_dir

            # ------------------------------------------------
            # Statistik
            # ------------------------------------------------

            success = 0
            skipped = 0
            failed = 0

            failed_rows = []

            self.ui_status(
                f"{total} Memories gefunden",
                f"0 / {total}"
            )

            # =================================================
            # DOWNLOADS
            # =================================================

            for index, item in enumerate(
                memories,
                start=1
            ):

                # --------------------------------------------
                # Abbruch prüfen
                # --------------------------------------------

                if self.cancel_event.is_set():
                    break

                # --------------------------------------------
                # Datensatz prüfen
                # --------------------------------------------

                if not isinstance(item, dict):

                    failed += 1

                    failed_rows.append(
                        f"{index}: Ungültiger JSON-Eintrag"
                    )

                    self.log(
                        f"[{index}/{total}] FEHLER: Ungültiger JSON-Eintrag"
                    )

                    continue

                # --------------------------------------------
                # Werte
                # --------------------------------------------

                date_value = item.get(
                    "Date",
                    ""
                )

                media_type = item.get(
                    "Media Type",
                    "UNKNOWN"
                )

                link_value = item.get(
                    "Download Link",
                    ""
                )

                # --------------------------------------------
                # Link
                # --------------------------------------------

                url = extract_url(
                    link_value
                )

                self.ui_progress(
                    (index - 1) / total,
                    index - 1,
                    total,
                    f"{date_value} | {media_type}"
                )

                # --------------------------------------------
                # Kein Link
                # --------------------------------------------

                if not url:

                    failed += 1

                    error_message = (
                        f"{index}: Kein Download-Link | "
                        f"{date_value}"
                    )

                    failed_rows.append(
                        error_message
                    )

                    self.log(
                        f"[{index}/{total}] FEHLER: "
                        "Kein gültiger Download-Link"
                    )

                    continue

                # --------------------------------------------
                # Download
                # --------------------------------------------

                part_file = None

                try:

                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": USER_AGENT
                        }
                    )

                    with urllib.request.urlopen(
                        request,
                        timeout=TIMEOUT
                    ) as response:

                        # ------------------------------------
                        # MIME-Type
                        # ------------------------------------

                        content_type = response.headers.get(
                            "Content-Type",
                            ""
                        )

                        # ------------------------------------
                        # Fehlerseite erhalten?
                        # ------------------------------------

                        if is_invalid_content_type(
                            content_type
                        ):
                            raise ValueError(
                                "Unerwarteter Inhaltstyp: "
                                f"{content_type}"
                            )

                        # ------------------------------------
                        # Dateiendung
                        # ------------------------------------

                        extension = extension_from_response(
                            content_type,
                            response.geturl(),
                            media_type
                        )

                        # ------------------------------------
                        # Dateiname
                        # ------------------------------------

                        base_name = (
                            f"{safe_date(date_value)}_"
                            f"{index:05d}_"
                            f"{str(media_type).lower()}"
                        )

                        filename = (
                            base_name + extension
                        )

                        target = os.path.join(
                            download_dir,
                            filename
                        )

                        # ------------------------------------
                        # Bereits vorhanden?
                        # ------------------------------------

                        if (
                            not zip_mode
                            and self.skip_existing_var.get()
                            and os.path.exists(target)
                            and os.path.getsize(target) > 0
                        ):

                            skipped += 1

                            self.log(
                                f"[{index}/{total}] "
                                f"Übersprungen: {filename}"
                            )

                            self.ui_progress(
                                index / total,
                                index,
                                total,
                                (
                                    f"Erfolgreich: {success}    "
                                    f"Übersprungen: {skipped}    "
                                    f"Fehler: {failed}"
                                )
                            )

                            continue

                        # ------------------------------------
                        # Temporäre Datei
                        # ------------------------------------

                        part_file = (
                            target + ".part"
                        )

                        # ------------------------------------
                        # Datei herunterladen
                        # ------------------------------------

                        with open(
                            part_file,
                            "wb"
                        ) as output_file:

                            while True:

                                if self.cancel_event.is_set():
                                    raise InterruptedError(
                                        "Download abgebrochen"
                                    )

                                chunk = response.read(
                                    CHUNK_SIZE
                                )

                                if not chunk:
                                    break

                                output_file.write(
                                    chunk
                                )

                        # ------------------------------------
                        # Dateigröße prüfen
                        # ------------------------------------

                        if os.path.getsize(part_file) == 0:
                            raise ValueError(
                                "Leere Datei empfangen."
                            )

                        # ------------------------------------
                        # Download finalisieren
                        # ------------------------------------

                        os.replace(
                            part_file,
                            target
                        )

                        part_file = None

                        success += 1

                        self.log(
                            f"[{index}/{total}] "
                            f"OK: {filename}"
                        )

                # --------------------------------------------
                # Benutzer hat abgebrochen
                # --------------------------------------------

                except InterruptedError:

                    if (
                        part_file
                        and os.path.exists(part_file)
                    ):
                        try:
                            os.remove(part_file)
                        except OSError:
                            pass

                    break

                # --------------------------------------------
                # Downloadfehler
                # --------------------------------------------

                except Exception as error:

                    failed += 1

                    if (
                        part_file
                        and os.path.exists(part_file)
                    ):
                        try:
                            os.remove(part_file)
                        except OSError:
                            pass

                    failed_rows.append(
                        (
                            f"{index}: "
                            f"{date_value} | "
                            f"{media_type} | "
                            f"{error}"
                        )
                    )

                    self.log(
                        f"[{index}/{total}] "
                        f"FEHLER: {error}"
                    )

                # --------------------------------------------
                # Fortschritt aktualisieren
                # --------------------------------------------

                self.ui_progress(
                    index / total,
                    index,
                    total,
                    (
                        f"Erfolgreich: {success}    "
                        f"Übersprungen: {skipped}    "
                        f"Fehler: {failed}"
                    )
                )

            # =================================================
            # ABBRUCHSTATUS
            # =================================================

            canceled = (
                self.cancel_event.is_set()
            )

            # =================================================
            # ZIP ERSTELLEN
            # =================================================

            if zip_mode and not canceled:

                self.ui_status(
                    "ZIP-Datei wird erstellt ...",
                    f"{total} / {total}"
                )

                self.log(
                    "Erstelle ZIP-Datei ..."
                )

                zip_path = self.unique_zip_path(
                    os.path.join(
                        self.output_dir,
                        "snapchat_memories.zip"
                    )
                )

                with zipfile.ZipFile(
                    zip_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    allowZip64=True
                ) as zip_file:

                    files = sorted(
                        os.listdir(
                            download_dir
                        )
                    )

                    for filename in files:

                        if self.cancel_event.is_set():
                            canceled = True
                            break

                        full_path = os.path.join(
                            download_dir,
                            filename
                        )

                        if os.path.isfile(
                            full_path
                        ):
                            zip_file.write(
                                full_path,
                                arcname=filename
                            )

                # --------------------------------------------
                # Abgebrochene ZIP entfernen
                # --------------------------------------------

                if canceled:

                    if os.path.exists(zip_path):

                        try:
                            os.remove(
                                zip_path
                            )
                        except OSError:
                            pass

                else:

                    self.log(
                        f"ZIP erstellt: {zip_path}"
                    )

            # =================================================
            # FEHLERPROTOKOLL
            # =================================================

            if failed_rows:

                error_log_path = os.path.join(
                    self.output_dir,
                    "snapchat_download_fehler.txt"
                )

                with open(
                    error_log_path,
                    "w",
                    encoding="utf-8"
                ) as file:

                    file.write(
                        "\n".join(
                            failed_rows
                        )
                    )

                self.log(
                    f"Fehlerprotokoll: {error_log_path}"
                )

            # =================================================
            # FERTIG
            # =================================================

            if canceled:

                self.finish(
                    "Abgebrochen",
                    success,
                    skipped,
                    failed,
                    False
                )

            else:

                self.ui_progress(
                    1,
                    total,
                    total,
                    (
                        f"Erfolgreich: {success}    "
                        f"Übersprungen: {skipped}    "
                        f"Fehler: {failed}"
                    )
                )

                self.finish(
                    "Fertig",
                    success,
                    skipped,
                    failed,
                    True
                )

        # ====================================================
        # JSON-FEHLER
        # ====================================================

        except json.JSONDecodeError as error:

            self.fatal(
                "Die JSON-Datei ist ungültig:\n\n"
                f"{error}"
            )

        # ====================================================
        # SONSTIGER FEHLER
        # ====================================================

        except Exception as error:

            self.fatal(
                str(error)
            )

        # ====================================================
        # TEMP-ORDNER AUFRÄUMEN
        # ====================================================

        finally:

            if temp_dir:

                shutil.rmtree(
                    temp_dir,
                    ignore_errors=True
                )

    # ========================================================
    # EINDEUTIGEN ZIP-NAMEN ERZEUGEN
    # ========================================================

    def unique_zip_path(
        self,
        path
    ):

        if not os.path.exists(path):
            return path

        stem, extension = os.path.splitext(
            path
        )

        counter = 2

        while os.path.exists(
            f"{stem}_{counter}{extension}"
        ):
            counter += 1

        return (
            f"{stem}_{counter}{extension}"
        )

    # ========================================================
    # FORTSCHRITT AKTUALISIEREN
    # ========================================================

    def ui_progress(
        self,
        value,
        current,
        total,
        detail
    ):

        value = max(
            0,
            min(
                1,
                value
            )
        )

        self.after(
            0,
            lambda value=value:
            self.progress.set(value)
        )

        self.after(
            0,
            lambda current=current, total=total:
            self.count_var.set(
                f"{current} / {total}"
            )
        )

        self.after(
            0,
            lambda detail=detail:
            self.detail_label.configure(
                text=detail
            )
        )

    # ========================================================
    # STATUS AKTUALISIEREN
    # ========================================================

    def ui_status(
        self,
        status,
        count=None
    ):

        self.after(
            0,
            lambda status=status:
            self.status_var.set(
                status
            )
        )

        if count is not None:

            self.after(
                0,
                lambda count=count:
                self.count_var.set(
                    count
                )
            )

    # ========================================================
    # LOG
    # ========================================================

    def log(
        self,
        text
    ):

        def append_log():

            self.log_box.configure(
                state="normal"
            )

            self.log_box.insert(
                "end",
                text + "\n"
            )

            self.log_box.see(
                "end"
            )

            self.log_box.configure(
                state="disabled"
            )

        self.after(
            0,
            append_log
        )

    # ========================================================
    # LOG LEEREN
    # ========================================================

    def clear_log(self):

        self.log_box.configure(
            state="normal"
        )

        self.log_box.delete(
            "1.0",
            "end"
        )

        self.log_box.configure(
            state="disabled"
        )

    # ========================================================
    # FERTIG
    # ========================================================

    def finish(
        self,
        status,
        success,
        skipped,
        failed,
        show_message
    ):

        def done():

            self.running = False

            self.status_var.set(
                status
            )

            self.start_button.configure(
                state="normal"
            )

            self.cancel_button.configure(
                state="disabled"
            )

            if show_message:

                messagebox.showinfo(
                    APP_TITLE,
                    (
                        "Download abgeschlossen.\n\n"
                        f"Erfolgreich: {success}\n"
                        f"Übersprungen: {skipped}\n"
                        f"Fehlgeschlagen: {failed}"
                    )
                )

        self.after(
            0,
            done
        )

    # ========================================================
    # FATALER FEHLER
    # ========================================================

    def fatal(
        self,
        message
    ):

        def show_error():

            self.running = False

            self.status_var.set(
                "Fehler"
            )

            self.start_button.configure(
                state="normal"
            )

            self.cancel_button.configure(
                state="disabled"
            )

            messagebox.showerror(
                APP_TITLE,
                message
            )

        self.after(
            0,
            show_error
        )

    # ========================================================
    # PROGRAMM SCHLIESSEN
    # ========================================================

    def on_close(self):

        if self.running:

            answer = messagebox.askyesno(
                APP_TITLE,
                (
                    "Ein Download läuft noch.\n\n"
                    "Möchtest du die Anwendung wirklich beenden?"
                )
            )

            if not answer:
                return

            self.cancel_event.set()

        self.destroy()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    app = SnapchatDownloaderApp()

    app.mainloop()