# Snapchat Memories Downloader

Eine kleine Desktop-Anwendung zum automatischen Herunterladen von
Snapchat Memories aus einer Snapchat-Export-JSON-Datei.

## Funktionen

- Snapchat JSON-Datei auswählen
- Zielordner auswählen
- Fotos und Videos automatisch herunterladen
- Dateien nach Datum benennen
- Optional als ZIP-Datei speichern
- Fortschrittsanzeige
- Fehlgeschlagene Downloads protokollieren
- Bereits heruntergeladene Dateien überspringen

## Windows

Die Anwendung kann mit PyInstaller als Windows-EXE erstellt werden.

```powershell
py -m pip install -r requirements.txt

py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name SnapchatMemoriesDownloader `
  snapchat_download.py