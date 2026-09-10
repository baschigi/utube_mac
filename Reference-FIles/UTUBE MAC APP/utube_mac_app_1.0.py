#!/usr/bin/env python3
import html
import hashlib
import json
import mimetypes
import os
import re
import shutil
import shlex
import subprocess
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SUPPORT = Path.home() / "Library/Application Support/UTUBE-MAC"
SCRIPTS = SUPPORT / "scripts"
LOGS = SUPPORT / "History/Logs"
GENERAL = SUPPORT / "Settings/General"
DOWNLOADS = Path((GENERAL / "downloads_directory.txt").read_text().strip()) if (GENERAL / "downloads_directory.txt").exists() else Path.home() / "Downloads/UTUBE-MAC"
INSTALLER = SCRIPTS / "install_utube_tools.sh"
UPDATER = SCRIPTS / "update_utube_tools.sh"
DOWNLOADER = SCRIPTS / "utube_media_download.sh"
HISTORY = SUPPORT / "History"
SCRIPT_HISTORY = HISTORY / "Script History"
SHORTCUT_HISTORY = HISTORY / "Shortcut Versions"
SETTINGS = SUPPORT / "Settings"
RUNTIME = SUPPORT / "Runtime"
REPOSITORY = SUPPORT / "GitHub Repository"
DOWNLOAD_HISTORY = HISTORY / "Download History" / "DOWNLOAD-HISTORY.txt"
MEDIA_SOURCE_INDEX = HISTORY / "Download History" / "MEDIA-SOURCE-INDEX.tsv"
SAFARI_EXTENSION = SUPPORT / "Safari Extension"
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/baschigi/utube_mac/main/Reference-FIles/utube-mac-version.txt"
LIBRARIES_FILE = GENERAL / "download-libraries.json"
DEFAULT_LIBRARY = Path.home() / "Downloads/UTUBE-MAC"
APPLE_MUSIC_LIBRARY = Path.home() / "Music/Music/Media.localized/Automatically Add to Music.localized"
PROTECTED_LIBRARIES = {str(DEFAULT_LIBRARY), str(APPLE_MUSIC_LIBRARY)}

def open_targets():
    targets = {
        "support": SUPPORT, "scripts": SCRIPTS, "settings": SETTINGS, "history": HISTORY,
        "logs": LOGS, "script-history": SCRIPT_HISTORY, "shortcut-history": SHORTCUT_HISTORY,
        "repository": REPOSITORY, "runtime": RUNTIME, "temp": SUPPORT / "Temp",
        "downloads": DOWNLOADS, "dashboard": SUPPORT / "Developer Dashboard", "safari-extension": SAFARI_EXTENSION,
    }
    for folder in [SHORTCUT_HISTORY, SCRIPT_HISTORY]:
        if folder.exists():
            for item in folder.iterdir():
                if item.is_dir(): targets[f"version-{item.name}"] = item
    return targets

def safe_target_item(target, relative=""):
    root = open_targets().get(target)
    if not root: return None
    try:
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        return path if path.exists() else None
    except Exception: return None

def file_browser_page(target, relative=""):
    root = open_targets().get(target); path = safe_target_item(target, relative)
    if not root or not path: return layout("UTUBE MAC – Dateizentrale", "Der angefragte Ordner ist nicht verfügbar.", '<section class="panel"><a href="/developer">← Zur Entwicklung</a></section>')
    if path.name == "DOWNLOAD-HISTORY.txt": return download_history_page(path, target, relative)
    back = urllib.parse.quote(str(Path(relative).parent)) if relative else ""
    heading = path.name if relative else next((name for name, key in [("UTUBE MAC – Application Support", "support"), ("Skripte", "scripts"), ("Einstellungen", "settings"), ("Gesamte Historie", "history"), ("Setup-Berichte", "logs"), ("Skript-Historie", "script-history"), ("Shortcut-Versionen", "shortcut-history")] if key == target), root.name)
    if path.is_dir():
        entries = []
        for item in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if item.name.startswith("."): continue
            child = str(Path(relative) / item.name) if relative else item.name
            icon = "Ordner" if item.is_dir() else (item.suffix.upper()[1:] or "Datei")
            entries.append(f'<a class="file-entry" href="/browse?target={urllib.parse.quote(target)}&path={urllib.parse.quote(child)}"><span><b>{html.escape(item.name)}</b><small>{icon}</small></span><span>›</span></a>')
        body = f'<section class="panel"><a href="/developer">← Zur Entwicklung</a><h2>{html.escape(heading)}</h2><p class="sub">Dateien zuerst direkt in UTUBE MAC ansehen.</p><div class="file-list">{"".join(entries) or "<p class=\"sub\">Dieser Ordner ist leer.</p>"}</div></section>'
        return layout("UTUBE MAC – Dateizentrale", "Lokale Dateien und Versionen in der App ansehen.", body)
    is_text = path.suffix.lower() in {".txt", ".log", ".sh", ".py", ".md", ".json", ".yaml", ".yml", ""} and path.stat().st_size <= 350000
    preview = html.escape(path.read_text(errors="replace")) if is_text else "Für diesen Dateityp ist keine Textvorschau verfügbar."
    controls = f'<div class="actions"><a class="folder" href="/browse?target={urllib.parse.quote(target)}&path={back}">← Zum Ordner</a><a class="folder" href="/reveal-file?target={urllib.parse.quote(target)}&path={urllib.parse.quote(relative)}">Im Finder zeigen</a>'
    if path.suffix.lower() == ".shortcut": controls += f'<a class="folder" href="/launch-file?target={urllib.parse.quote(target)}&path={urllib.parse.quote(relative)}">Kurzbefehl hinzufügen</a>'
    controls += "</div>"
    log_summary = ""
    if path.suffix.lower() == ".log" and is_text:
        lines = [line.strip() for line in path.read_text(errors="replace").splitlines() if line.strip()]
        state = "Abgeschlossen" if any(word in " ".join(lines).lower() for word in ("fertig", "completed", "erfolgreich")) else "Protokoll"
        log_summary = f'<section class="grid">{card("Protokollstatus", state)}{card("Einträge", str(len(lines)))}{card("Letzte Änderung", time.strftime("%d.%m.%Y · %H:%M", time.localtime(path.stat().st_mtime)))}</section>'
    return layout("UTUBE MAC – Datei", "Vorschau aus deiner lokalen UTUBE-MAC-Dateizentrale.", f'{log_summary}<section class="panel"><h2>{html.escape(path.name)}</h2>{controls}<pre class="code-preview">{preview}</pre></section>')

def history_field(block, name):
    match = re.search(rf"^\s*{re.escape(name)}:\s*(.+)$", block, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""

def download_history_page(history, target, relative):
    raw = history.read_text(errors="replace")
    entries = []
    for block in re.split(r"\nMEDIA FILE \d+\n", raw)[1:]:
        file_path, title, url = history_field(block, "File"), history_field(block, "Title"), history_field(block, "URL")
        if not file_path or not title: continue
        media = safe_media(file_path); fmt = history_field(block, "Format") or (Path(file_path).suffix[1:].upper())
        size = history_field(block, "File size"); modified = history_field(block, "File modified")
        thumbnail = thumbnail_for(Path(file_path), url)
        poster = f' poster="{html.escape(thumbnail, quote=True)}"' if thumbnail else ""
        if media and media.suffix.lower() in {".mp3", ".m4a", ".opus", ".flac", ".aac", ".ogg"}: player = f'<audio controls src="{media_url(media)}"></audio>'
        elif media: player = f'<video controls preload="metadata"{poster} src="{media_url(media)}"></video>'
        elif thumbnail: player = f'<img class="audio-art" src="{html.escape(thumbnail, quote=True)}" alt="Vorschaubild">'
        else: player = '<div class="missing-preview">Datei nicht mehr am gespeicherten Ort</div>'
        local_button = f'<a class="folder" href="/library">Lokal abspielen</a>' if media else '<span class="hint">Lokale Datei nicht gefunden</span>'
        youtube_button = f'<a class="folder" target="_blank" rel="noopener" href="{html.escape(url, quote=True)}">Auf YouTube öffnen</a>' if url.startswith("http") else ""
        entries.append(f'<article class="media-card media-{fmt.lower()}">{player}<span class="type-badge {fmt.lower()}">{html.escape(fmt)}</span><b>{html.escape(title)}</b><small>{html.escape(size)} · {html.escape(modified)}</small><div class="actions compact">{local_button}{youtube_button}<a class="folder" href="/reveal?path={urllib.parse.quote(file_path)}">Im Finder zeigen</a></div></article>')
    successful = raw.count("Result: Completed") + raw.count("Recovered existing media files")
    body = f'<section class="grid">{card("Historische Medien", str(len(entries)))}{card("Erfolgreiche Durchläufe", str(successful))}</section><section class="panel"><a href="/browse?target={urllib.parse.quote(target)}&path={urllib.parse.quote(str(Path(relative).parent))}">← Zum Ordner</a><h2>Download-Verlauf als Mediathek</h2><p class="sub">Gespeicherte Quellen, lokale Dateien und technische Details auf einen Blick.</p><div class="media-grid">{"".join(entries) or "<p class=\"sub\">Noch keine Medien im Verlauf gefunden.</p>"}</div></section>'
    return layout("UTUBE MAC – Download-Verlauf", "Interaktive Übersicht deiner UTUBE-MAC-Medien.", body)

def safari_extension_guide_page():
    body = '''<section class="panel"><h2>Safari-Erweiterung einrichten</h2><p class="sub">Die Erweiterung fügt auf YouTube einen Button „Zu UTUBE MAC hinzufügen“ hinzu. Sie schickt nur den gerade geöffneten YouTube-Link an deine lokale Warteschlange.</p><div class="grid"><div class="card"><div class="label">1 · Erweiterung installieren</div><div class="value">UTUBE MAC Extension</div><p class="hint">Öffne die vorbereitete Begleit-App.</p></div><div class="card"><div class="label">2 · Safari öffnen</div><div class="value">Safari-Einstellungen</div><p class="hint">Safari → Einstellungen → Erweiterungen</p></div><div class="card"><div class="label">3 · Einmal aktivieren</div><div class="value">UTUBE MAC einschalten</div><p class="hint">Danach erscheint der Button auf YouTube-Videos und Playlists.</p></div></div><div class="actions"><a class="folder" href="/install-safari-extension">Erweiterung installieren</a><a class="folder" href="/open?target=safari-extension">Erweiterungsdateien zeigen</a><a class="folder" href="/">Zurück zu UTUBE MAC</a></div><p class="hint">Safari verlangt diese eine Aktivierung selbst. UTUBE MAC kann sie nicht heimlich einschalten.</p></section>'''
    return layout("UTUBE MAC – Safari-Erweiterung", "Geführte Einrichtung für den YouTube-Queue-Button.", body)

def run_in_terminal(arguments):
    apple = '''on run argv
tell application "Terminal"
activate
do script item 1 of argv & " " & quoted form of item 2 of argv & " " & quoted form of item 3 of argv & " " & quoted form of item 4 of argv & " " & quoted form of item 5 of argv
end tell
end run'''
    command_prefix = "/bin/bash " + shlex.quote(str(arguments[0]))
    if Path(arguments[0]) == DOWNLOADER:
        command_prefix = "/usr/bin/env UTUBE_MAC_FORCE_DASHBOARD=1 " + command_prefix
    values = [command_prefix] + [str(value) for value in arguments[1:]]
    values += [""] * (5 - len(values))
    subprocess.Popen(["osascript", "-"] + values[:5], stdin=subprocess.PIPE, text=True).communicate(apple)

def run_silently(script):
    subprocess.Popen(["/bin/bash", str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def run_download_in_background(mode, url, quality, subtitles):
    jobs = RUNTIME / "Download Progress" / "Jobs"; jobs.mkdir(parents=True, exist_ok=True)
    job_id = subprocess.check_output(["date", "+%Y%m%d-%H%M%S"], text=True).strip() + f"-{os.getpid()}"
    log = jobs / f"{job_id}.log"
    with log.open("w") as output:
        subprocess.Popen(["/usr/bin/env", "UTUBE_MAC_DOWNLOAD_WORKER=1", f"UTUBE_MAC_JOB_ID={job_id}", "/bin/bash", str(DOWNLOADER), mode, url, quality, subtitles], stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return job_id

def run_queue_in_terminal(items):
    queue_file = SUPPORT / "Temp" / "utube-mac-download-queue.sh"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#!/bin/bash", "set -e"]
    for item in items:
        lines.append("/bin/bash " + " ".join(shlex.quote(str(value)) for value in [DOWNLOADER, item["mode"], item["url"], item["quality"], item["subtitles"]]))
    queue_file.write_text("\n".join(lines) + "\n")
    queue_file.chmod(0o755)
    run_in_terminal([queue_file])

def find_tool(command):
    paths = [Path("/opt/homebrew/bin") / command, Path("/usr/local/bin") / command]
    for path in paths:
        if path.exists(): return str(path)
    return command

def tool_version(command, argument):
    try:
        return subprocess.check_output([find_tool(command), argument], text=True, stderr=subprocess.DEVNULL).splitlines()[0]
    except Exception:
        return "Nicht installiert"

def local_version():
    version_file = GENERAL / "utube-mac-version.txt"
    return version_file.read_text().strip() if version_file.exists() else "Nicht verfügbar"

def library_locations():
    try: saved = json.loads(LIBRARIES_FILE.read_text())
    except Exception: saved = []
    paths = [str(DOWNLOADS), str(DEFAULT_LIBRARY), str(APPLE_MUSIC_LIBRARY)] + [str(item) for item in saved if isinstance(item, str)]
    return list(dict.fromkeys(paths))

def remember_library(path):
    location = str(Path(path).expanduser())
    existing = library_locations()
    if location not in existing: existing.append(location)
    GENERAL.mkdir(parents=True, exist_ok=True); LIBRARIES_FILE.write_text(json.dumps(existing, indent=2))
    return location

def forget_library(path):
    if str(path) in PROTECTED_LIBRARIES: return
    remaining = [item for item in library_locations() if item != str(path)]
    LIBRARIES_FILE.write_text(json.dumps(list(dict.fromkeys(remaining)), indent=2))

def choose_library_folder():
    script = 'set chosenFolder to choose folder with prompt "UTUBE MAC: Download-Ordner auswählen"\nreturn POSIX path of chosenFolder'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""

def newer_version(available, installed):
    try: return tuple(map(int, available.split("."))) > tuple(map(int, installed.split(".")))
    except Exception: return False

def remote_update():
    cache = SUPPORT / "Temp" / "remote-version-cache.txt"
    try:
        if cache.exists() and (time.time() - cache.stat().st_mtime) < 300: available = cache.read_text().strip()
        else:
            available = urllib.request.urlopen(REMOTE_VERSION_URL, timeout=2).read().decode().strip()
            cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(available)
        return available if newer_version(available, local_version()) else ""
    except Exception: return ""

def library_stats():
    groups = {"MP4": DOWNLOADS / "MP4", "MKV": DOWNLOADS / "MKV", "MP3": DOWNLOADS / "MP3"}
    extensions = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".flac", ".aac", ".ogg"}
    counts = {name: sum(1 for item in folder.rglob("*") if item.is_file() and item.suffix.lower() in extensions) if folder.exists() else 0 for name, folder in groups.items()}
    try:
        free = shutil.disk_usage(DOWNLOADS).free // (1024 * 1024 * 1024)
    except Exception:
        free = 0
    return counts, free

def library_chart():
    counts, _ = library_stats()
    maximum = max(1, *counts.values())
    colors = {"MP4": "#6ea8fe", "MKV": "#b28cff", "MP3": "#55d6a8"}
    return "".join(f'<a class="bar-item" href="/library?filter={name}"><div class="bar-label"><span>{name}</span><b>{amount}</b></div><div class="bar-track"><div class="bar" style="width:{max(8, amount * 100 // maximum)}%;background:{colors[name]}"></div></div></a>' for name, amount in counts.items())

def media_files():
    extensions = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".flac", ".aac", ".ogg"}
    return sorted((p for p in DOWNLOADS.rglob("*") if p.is_file() and p.suffix.lower() in extensions), key=lambda p: p.stat().st_mtime, reverse=True)

def safe_media(value):
    try:
        path = Path(value).resolve(); path.relative_to(DOWNLOADS.resolve()); return path if path.is_file() else None
    except Exception: return None

def media_url(path): return "/media?path=" + urllib.parse.quote(str(path))

def readable_size(size):
    if size >= 1024 ** 3: return f"{size / 1024 ** 3:.2f} GB"
    if size >= 1024 ** 2: return f"{size / 1024 ** 2:.0f} MB"
    return f"{size / 1024:.0f} KB"

def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def duplicate_groups(files):
    by_size = {}
    for path in files:
        by_size.setdefault(path.stat().st_size, []).append(path)
    groups = []
    for same_size in by_size.values():
        if len(same_size) < 2: continue
        by_hash = {}
        for path in same_size:
            try: by_hash.setdefault(file_digest(path), []).append(path)
            except OSError: pass
        groups.extend(group for group in by_hash.values() if len(group) > 1)
    return sorted(groups, key=lambda group: sum(path.stat().st_size for path in group), reverse=True)

def normal_title(value):
    return "".join(char.lower() for char in value if char.isalnum())

def source_url_for(path):
    try:
        identity = f"{path.stat().st_dev}:{path.stat().st_ino}"
        if MEDIA_SOURCE_INDEX.exists():
            for line in reversed(MEDIA_SOURCE_INDEX.read_text(errors="replace").splitlines()):
                parts = line.split("\t", 2)
                if len(parts) >= 2 and parts[0] == identity and parts[1].startswith("http"): return parts[1]
    except OSError: pass
    if not DOWNLOAD_HISTORY.exists(): return ""
    wanted = normal_title(path.stem)
    blocks = DOWNLOAD_HISTORY.read_text(errors="replace").split("------------------------------------------------------------")
    for block in reversed(blocks):
        title = next((line[7:] for line in block.splitlines() if line.startswith("Title: ")), "")
        url = next((line[5:] for line in block.splitlines() if line.startswith("URL: ")), "")
        if url and (wanted == normal_title(title) or wanted in normal_title(title) or normal_title(title) in wanted):
            source = url.strip()
            try:
                MEDIA_SOURCE_INDEX.parent.mkdir(parents=True, exist_ok=True)
                with MEDIA_SOURCE_INDEX.open("a") as index: index.write(f"{path.stat().st_dev}:{path.stat().st_ino}\t{source}\t{path}\n")
            except OSError: pass
            return source
    return ""

def thumbnail_for(path, source_url=""):
    for extension in (".webp", ".jpg", ".jpeg", ".png"):
        candidate = path.with_suffix(extension)
        if candidate.exists(): return media_url(candidate)
    match = re.search(r"(?:[?&]v=|youtu\.be/|shorts/)([^?&/]+)", source_url)
    return f"https://i.ytimg.com/vi/{match.group(1)}/hqdefault.jpg" if match else ""

def progress_jobs():
    jobs = RUNTIME / "Download Progress" / "Jobs"; results = []
    if not jobs.exists(): return results
    for status in sorted(jobs.glob("*.status"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
        data = {}
        for line in status.read_text(errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1); data[key] = value
        job_id = status.stem
        data["id"] = job_id; data["active"] = (jobs / f"{job_id}.active").exists(); data["done"] = (jobs / f"{job_id}.done").exists()
        results.append(data)
    return results

def setup_progress():
    logs = sorted(LOGS.glob("setup-*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not logs: return {"ready": False, "stage": "Einrichtung wird vorbereitet", "lines": []}
    log = logs[0]
    raw = log.read_text(errors="replace")[-18000:]
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw).replace("\r", "\n")
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    stage_lines = [line for line in lines if "SCHRITT" in line and "VON 8" in line]
    meaningful = [line for line in lines if any(token in line.lower() for token in ("✅", "⚠", "❌", "ℹ", "⠹", "install", "homebrew", "yt-dlp", "ffmpeg", "apple-werkzeuge", "musicbrainz", "aktualis"))]
    stage = stage_lines[-1] if stage_lines else "Einrichtung läuft"
    done = any("einrichtung abgeschlossen" in line.lower() or "alles ist bereit" in line.lower() for line in lines[-30:])
    failed = any("einrichtung wurde nicht abgeschlossen" in line.lower() for line in lines[-20:])
    return {"ready": True, "stage": stage, "lines": meaningful[-7:], "done": done, "failed": failed, "log": log.name}

def library_page(initial_filter="ALL"):
    cards = []
    for path in media_files():
        kind = "audio" if path.suffix.lower() in {".mp3", ".m4a", ".opus", ".flac", ".aac", ".ogg"} else "video"
        file_type = "MP3" if kind == "audio" else ("MKV" if path.suffix.lower() == ".mkv" else "MP4")
        source_url = source_url_for(path)
        thumbnail = thumbnail_for(path, source_url)
        poster = f' poster="{html.escape(thumbnail, quote=True)}"' if thumbnail else ""
        artwork = f'<img class="audio-art" src="{html.escape(thumbnail, quote=True)}" alt="Vorschaubild">' if kind == "audio" and thumbnail else ""
        player = f'<audio controls src="{media_url(path)}"></audio>' if kind == "audio" else f'<video controls preload="metadata"{poster} src="{media_url(path)}"></video>'
        alternative = "MP4-Video laden" if kind == "audio" else "MP3-Audio laden"
        alternative_mode = "single-mp4" if kind == "audio" else "single-mp3"
        alternative_button = f'<button type="button" class="secondary alternative" onclick="downloadAlternative({json.dumps(source_url)}, {json.dumps(alternative_mode)})">{alternative}</button>' if source_url else '<span class="hint">Quell-Link für diese ältere Datei nicht gespeichert.</span>'
        cards.append(f'<article class="media-card media-{file_type.lower()}" data-type="{file_type}">{artwork}{player}<span class="type-badge {file_type.lower()}">{file_type}</span><b>{html.escape(path.stem)}</b><small>{html.escape(path.suffix.upper()[1:])} · {readable_size(path.stat().st_size)}</small><div class="actions compact"><a class="folder" href="/reveal?path={urllib.parse.quote(str(path))}">Im Finder zeigen</a>{alternative_button}<form method="post" action="/action" onsubmit="return confirm(\'Diese Datei in den Papierkorb legen?\');"><input type="hidden" name="action" value="trash"><input type="hidden" name="path" value="{html.escape(str(path), quote=True)}"><button type="submit" class="danger">Papierkorb</button></form></div></article>')
    filters = '<div class="filters"><button class="filter active" type="button" data-filter="ALL">Alle</button><button class="filter mp3" type="button" data-filter="MP3">MP3 / Audio</button><button class="filter mp4" type="button" data-filter="MP4">MP4 / Video</button><button class="filter mkv" type="button" data-filter="MKV">MKV</button></div>'
    selected_filter = json.dumps(initial_filter if initial_filter in {"ALL", "MP3", "MP4", "MKV"} else "ALL")
    script = '''<script>function setFilter(choice){document.querySelectorAll('.filter').forEach(button=>{button.classList.toggle('active',button.dataset.filter===choice)});document.querySelectorAll('.media-card').forEach(card=>card.style.display=(choice==='ALL'||card.dataset.type===choice)?'grid':'none')}document.querySelectorAll('.filter').forEach(button=>button.onclick=()=>setFilter(button.dataset.filter));setFilter(__FILTER__);async function downloadAlternative(url,mode){if(!url){alert('Für diese Datei ist kein gespeicherter YouTube-Link vorhanden.');return}if(!confirm('Alternative Version im Hintergrund laden?'))return;let r=await fetch('/download-background',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,mode,quality:'best',subtitles:'none'})});if(r.ok){location.href='/?message=Alternative%20Version%20wurde%20gestartet.'}else alert('Download konnte nicht gestartet werden.') }</script>'''.replace("__FILTER__", selected_filter)
    return layout("UTUBE MAC – Mediathek", "Abspielen, anhören und im Finder verwalten.", '<section class="panel"><a href="/">← Zurück</a><h2>Deine Downloads</h2>' + filters + '<div class="media-grid">' + "".join(cards or ['<p class="sub">Noch keine Medien vorhanden.</p>']) + "</div></section>" + script)

def storage_page():
    files = media_files(); total = sum(p.stat().st_size for p in files); largest = sorted(files, key=lambda p:p.stat().st_size, reverse=True)[:15]; duplicates = duplicate_groups(files)
    rows = "".join(f'<article class="file-row"><div><b>{html.escape(p.name)}</b><small>{readable_size(p.stat().st_size)} · {html.escape(str(p.relative_to(DOWNLOADS)))}</small></div><div class="row-actions"><a href="/reveal?path={urllib.parse.quote(str(p))}">Im Finder</a><form method="post" action="/action" onsubmit="return confirm(\'Diese Datei in den Papierkorb legen?\');"><input type="hidden" name="action" value="trash"><input type="hidden" name="path" value="{html.escape(str(p), quote=True)}"><button class="danger">Papierkorb</button></form></div></article>' for p in largest)
    duplicate_html = ""
    for index, group in enumerate(duplicates, 1):
        size = group[0].stat().st_size
        members = "".join(f'<article class="file-row"><div><b>{html.escape(p.name)}</b><small>{html.escape(str(p.relative_to(DOWNLOADS)))}</small></div><div class="row-actions"><a href="/reveal?path={urllib.parse.quote(str(p))}">Im Finder</a><form method="post" action="/action" onsubmit="return confirm(\'Diese doppelte Datei in den Papierkorb legen?\');"><input type="hidden" name="action" value="trash"><input type="hidden" name="path" value="{html.escape(str(p), quote=True)}"><button class="danger">Papierkorb</button></form></div></article>' for p in group)
        duplicate_html += f'<div class="duplicate-group"><b>Duplikat-Gruppe {index} · {len(group)} identische Dateien · jeweils {readable_size(size)}</b>{members}</div>'
    duplicate_card = card("Exakte Duplikate", str(sum(len(group) - 1 for group in duplicates)), "Vollständig verglichen – nur identische Dateien.")
    return layout("UTUBE MAC – Speicheranalyse", "Finde große Dateien und exakte Duplikate. Jede Bereinigung fragt einzeln nach.", f'<section class="grid">{card("Mediendateien", str(len(files)))}{card("Belegter Speicher", readable_size(total))}{duplicate_card}</section><section class="panel"><a href="/">← Zurück</a><h2>Größte Downloads</h2><div class="file-list">{rows or "<p class=\"sub\">Keine Dateien vorhanden.</p>"}</div></section><section class="panel"><h2>Exakte Duplikate</h2><p class="sub">Diese Dateien wurden nach Inhalt verglichen, nicht nur nach Namen. Lege nur die Kopie in den Papierkorb, die du nicht behalten möchtest.</p>{duplicate_html or "<p class=\"message\">Keine exakten Duplikate gefunden.</p>"}</section>')

def safari_youtube_tabs():
    script = '''tell application "Safari"
    set output to ""
    repeat with w in windows
        repeat with t in tabs of w
            set tabURL to URL of t
            if (tabURL contains "youtube.com/watch?v=") or (tabURL contains "youtube.com/shorts/") or (tabURL contains "youtube.com/playlist?list=") or (tabURL contains "youtu.be/") then
                set output to output & (name of t) & (ASCII character 9) & tabURL & linefeed
            end if
        end repeat
    end repeat
    return output
end tell'''
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return [{"title": title.strip() or "YouTube", "url": url.strip()} for line in result.stdout.splitlines() if "\t" in line for title, url in [line.split("\t", 1)] if url.strip().startswith("http")]
    except Exception:
        return []

def health():
    rows = []
    for file in [INSTALLER, UPDATER, DOWNLOADER]:
        result = subprocess.run(["bash", "-n", str(file)], capture_output=True, text=True) if file.exists() else None
        rows.append((file.name, "Bereit" if result and result.returncode == 0 else "Fehlt oder fehlerhaft"))
    return rows

def card(label, value, note=""):
    return f'<div class="card"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div><div class="note">{html.escape(note)}</div></div>'

def safari_extension_status():
    heartbeat = RUNTIME / "Safari Extension Heartbeat.json"
    if heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 300:
        return "Aktiv auf YouTube", "Die Safari-Erweiterung hat sich gerade bei UTUBE MAC gemeldet."
    return "Noch nicht bestätigt", "Nicht aktiviert oder gerade nicht auf einer YouTube-Seite geöffnet."

def layout(title, subtitle, content, message=""):
    message_html = f'<div class="message">{html.escape(message)}</div>' if message else ""
    theme_styles = '''<style>
body[data-theme="midnight"]{background:radial-gradient(circle at 14% -12%,#273d64 0,#101521 40%,#080a10 100%)}body[data-theme="midnight"] .card,body[data-theme="midnight"] .panel,body[data-theme="midnight"] .media-card{background:linear-gradient(135deg,#1b2638,#101721);border-color:#425875}body[data-theme="midnight"] button{background:linear-gradient(135deg,#3d8bff,#5a5fe8)}body[data-theme="midnight"] button.secondary,body[data-theme="midnight"] .folder,body[data-theme="midnight"] .file-entry{background:#1b2b40;border-color:#415f80}body[data-theme="midnight"] nav a{background:#21334a;border-color:#486887}body[data-theme="midnight"] .bar{filter:hue-rotate(20deg)}
body[data-theme="ember"]{background:radial-gradient(circle at 16% -14%,#823128 0,#261013 38%,#0d0708 100%)}body[data-theme="ember"] .card,body[data-theme="ember"] .panel,body[data-theme="ember"] .media-card{background:linear-gradient(135deg,#4a201f,#1d0e10);border-color:#bc5744}body[data-theme="ember"] button{background:linear-gradient(135deg,#ff6c45,#f1a52d)}body[data-theme="ember"] button.secondary,body[data-theme="ember"] .folder,body[data-theme="ember"] .file-entry{background:#5a2822;border-color:#dc7652;color:#fff4ec}body[data-theme="ember"] nav a{background:#59251f;border-color:#e27c53;color:#fff1e8}body[data-theme="ember"] input,body[data-theme="ember"] select{background:#1b0d0f;border-color:#d6684b;color:#fff1eb}body[data-theme="ember"] .bar{filter:hue-rotate(310deg)}body[data-theme="ember"] .type-badge.mp4{background:#b9482f;color:#fff8ee}body[data-theme="ember"] .type-badge.mp3{background:#536b2d;color:#f6ffcf}
body[data-theme="frost"]{background:linear-gradient(145deg,#f7fbff,#d5e9ff 50%,#edf7ff);color:#0d2339}body[data-theme="frost"] header{border-color:#78afd9}body[data-theme="frost"] .card,body[data-theme="frost"] .panel,body[data-theme="frost"] .media-card{background:linear-gradient(135deg,#ffffff,#e5f3ff);border-color:#71abd8;box-shadow:0 14px 32px #326d9a45}body[data-theme="frost"] .label{color:#1b5a88}body[data-theme="frost"] .sub,body[data-theme="frost"] .note,body[data-theme="frost"] small,body[data-theme="frost"] .hint{color:#345a79}body[data-theme="frost"] button{background:linear-gradient(135deg,#075db7,#1689e0)}body[data-theme="frost"] button.secondary,body[data-theme="frost"] .folder,body[data-theme="frost"] .file-entry{background:#cfe9ff;border-color:#5c9ed1;color:#0b426d}body[data-theme="frost"] nav a{background:#cbe8ff;border-color:#5b9fd2;color:#073f69}body[data-theme="frost"] input,body[data-theme="frost"] select{background:#fff;border:2px solid #5f9fce;color:#092e4a}body[data-theme="frost"] .bar-track{background:#b9d9f0}body[data-theme="frost"] .code-preview{background:#fff;color:#102f49;border-color:#77aed6}body[data-theme="frost"] .type-badge.mp4{background:#075db7;color:white}
body[data-theme="pearl"]{background:linear-gradient(145deg,#fffdfc,#f7dce7 50%,#fff7fa);color:#351321}body[data-theme="pearl"] header{border-color:#d98ba8}body[data-theme="pearl"] .card,body[data-theme="pearl"] .panel,body[data-theme="pearl"] .media-card{background:linear-gradient(135deg,#fffefe,#ffe7ef);border-color:#d986a4;box-shadow:0 14px 32px #a4476a45}body[data-theme="pearl"] .label{color:#8a204b}body[data-theme="pearl"] .sub,body[data-theme="pearl"] .note,body[data-theme="pearl"] small,body[data-theme="pearl"] .hint{color:#754258}body[data-theme="pearl"] button{background:linear-gradient(135deg,#a91354,#dd4c56)}body[data-theme="pearl"] button.secondary,body[data-theme="pearl"] .folder,body[data-theme="pearl"] .file-entry{background:#ffd7e4;border-color:#d57498;color:#751439}body[data-theme="pearl"] nav a{background:#ffd7e4;border-color:#d57498;color:#711034}body[data-theme="pearl"] input,body[data-theme="pearl"] select{background:#fff;border:2px solid #d16f92;color:#451427}body[data-theme="pearl"] .bar-track{background:#efbdd0}body[data-theme="pearl"] .code-preview{background:#fff;color:#492033;border-color:#da93ad}body[data-theme="pearl"] .type-badge.mp3{background:#a91354;color:#fff}
</style><script>(()=>{let picker=document.getElementById('theme-picker');if(!picker)return;picker.innerHTML='<option value="ocean">Ozean — dunkel</option><option value="midnight">Mitternacht — dunkel</option><option value="ember">Glut — dunkel</option><option value="frost">Frost — hell</option><option value="pearl">Perle — hell</option>';let saved=localStorage.getItem('utube-mac-theme')||'ocean';if(!['ocean','midnight','ember','frost','pearl'].includes(saved))saved='ocean';document.body.dataset.theme=saved;picker.value=saved;picker.onchange=()=>{document.body.dataset.theme=picker.value;localStorage.setItem('utube-mac-theme',picker.value)}})()</script>'''
    content = theme_styles + content
    return f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
body{{margin:0;background:radial-gradient(circle at 18% -10%,#173c5c 0,#0a1018 34%,#080b12 100%);color:#edf3f8;font:16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}.wrap{{max-width:1060px;margin:auto;padding:30px 20px 70px}}header{{display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid #29445b;padding-bottom:21px}}h1{{margin:0;font-size:30px;letter-spacing:-.04em}}h2{{font-size:19px;margin:0 0 12px}}.sub,.note{{color:#a8b8c9}}nav{{display:flex;gap:9px;flex-wrap:wrap}}nav a{{padding:9px 13px;background:#193148b8;border:1px solid #355778;border-radius:999px;color:#cae6ff;text-decoration:none;font-weight:700}}.grid,.media-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:18px 0}}.card,.panel,.media-card{{background:linear-gradient(135deg,#172a3cde,#0d1722e8);border:1px solid #2d4e69;border-radius:18px;padding:18px;box-shadow:0 18px 45px #0006}}.card{{position:relative;overflow:hidden}}.card:before{{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#5dd1ff,#7776ff,#55d6a8)}}.label{{color:#a5bdd0;font-size:11px;text-transform:uppercase;letter-spacing:.11em}}.value{{font-size:23px;font-weight:780;margin:8px 0}}.panel{{margin-top:16px}}.actions,.folders{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}.compact{{grid-template-columns:1fr 1fr}}button{{width:100%;border:0;border-radius:11px;padding:13px;background:linear-gradient(135deg,#4b8fff,#6974ff);color:white;font-weight:800;cursor:pointer}}button.secondary{{background:#203a53}}button.danger{{background:#572737;color:#ffd9df;padding:10px}}input,select{{box-sizing:border-box;width:100%;padding:12px;border-radius:11px;border:1px solid #365b77;background:#09131e;color:white;margin-bottom:10px}}input[type=checkbox]{{width:auto;margin:0 8px 0 0;accent-color:#6d8cff}}table{{width:100%;border-collapse:collapse}}td{{padding:10px;border-bottom:1px solid #2a455d}}.ok{{color:#6ee7a1}}.bad{{color:#ff8b8b}}a{{color:#8ed5ff;text-decoration:none}}.folder{{display:block;padding:12px;border:1px solid #365876;border-radius:11px;background:#15283a;color:#d7ecff;font-weight:700}}li{{margin:9px 0}}.message{{margin:18px 0;padding:13px;border:1px solid #2f8962;border-radius:12px;background:#123524;color:#b6ffd2}}.hint,small{{font-size:13px;color:#a7bacd}}.bar-item{{margin:13px 0}}.bar-label{{display:flex;justify-content:space-between;color:#c9d8e8;font-size:14px;margin-bottom:6px}}.bar-track{{height:10px;border-radius:999px;background:#07111b;overflow:hidden}}.bar{{height:100%;border-radius:999px}}.media-card{{display:grid;gap:10px;position:relative}}.media-mp3{{border-color:#357c63}}.media-mp4{{border-color:#3c6cb3}}.media-mkv{{border-color:#704ca4}}video,audio,.audio-art{{width:100%;max-height:180px;border-radius:10px;background:#070b10}}.audio-art{{height:150px;object-fit:cover}}.type-badge{{position:absolute;top:27px;right:27px;padding:5px 8px;border-radius:999px;font-size:11px;font-weight:850}}.type-badge.mp3{{background:#174d3b;color:#a6ffd9}}.type-badge.mp4{{background:#183f75;color:#b9d9ff}}.type-badge.mkv{{background:#4a286e;color:#e3ccff}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}}button.filter{{width:auto;background:#193148;padding:9px 12px}}button.filter.active{{outline:2px solid #7bb8ff}}button.filter.mp3{{color:#a6ffd9}}button.filter.mp4{{color:#b9d9ff}}button.filter.mkv{{color:#e3ccff}}.file-list,.duplicate-group{{display:grid;gap:9px}}.duplicate-group{{border-top:1px solid #294861;margin-top:18px;padding-top:16px}}.file-row{{display:flex;gap:14px;align-items:center;justify-content:space-between;padding:12px;border:1px solid #28445d;border-radius:12px;background:#0b1824}}.file-row small{{display:block;margin-top:4px;overflow-wrap:anywhere}}.row-actions{{display:flex;align-items:center;gap:10px;flex-shrink:0}}.row-actions form{{margin:0}}.row-actions a{{padding:8px 10px;background:#1b354c;border-radius:9px;font-weight:700}}.progress-box{{display:none;margin-top:14px;padding:14px;border:1px solid #426c97;border-radius:13px;background:#0a1928}}.progress-box.show{{display:block}}.progress-fill{{height:100%;min-width:3%;border-radius:999px;background:linear-gradient(90deg,#55d6a8,#5c8fff)}}.progress-meta{{display:flex;justify-content:space-between;gap:12px;color:#b5c8db;font-size:13px;margin-top:8px}}@media(max-width:600px){{.file-row{{align-items:flex-start;flex-direction:column}}.row-actions{{width:100%}}.row-actions>*{{flex:1}}}}
 .theme-picker{{width:auto;margin:0;padding:8px 10px;border-radius:999px;font-size:12px;font-weight:750}}body[data-theme="violet"]{{background:radial-gradient(circle at 15% -10%,#4e277a 0,#171029 36%,#090a14 100%)}}body[data-theme="violet"] .card,body[data-theme="violet"] .panel,body[data-theme="violet"] .media-card{{background:linear-gradient(135deg,#30204bde,#171124ed);border-color:#68418b}}body[data-theme="violet"] button{{background:linear-gradient(135deg,#9a62ee,#df59ad)}}body[data-theme="violet"] button.secondary,body[data-theme="violet"] .folder{{background:#372457;border-color:#76509e}}body[data-theme="violet"] nav a{{background:#362452;border-color:#70499a}}body[data-theme="forest"]{{background:radial-gradient(circle at 18% -10%,#155c48 0,#092019 35%,#07120f 100%)}}body[data-theme="forest"] .card,body[data-theme="forest"] .panel,body[data-theme="forest"] .media-card{{background:linear-gradient(135deg,#123f35df,#0a211d);border-color:#347767}}body[data-theme="forest"] button{{background:linear-gradient(135deg,#22a878,#2f9bc4)}}body[data-theme="forest"] button.secondary,body[data-theme="forest"] .folder{{background:#153e35;border-color:#367766}}body[data-theme="forest"] nav a{{background:#153c34;border-color:#347565}}</style></head><body><main class="wrap"><header><div><h1>{html.escape(title)}</h1><p class="sub">{html.escape(subtitle)}</p></div><nav><a href="/">UTUBE MAC</a><a href="/developer">Entwicklung</a><select id="theme-picker" class="theme-picker" aria-label="Design auswählen"><option value="ocean">Ozean</option><option value="violet">Violett</option><option value="forest">Wald</option></select></nav></header>{message_html}{content}<script>(()=>{{let p=document.getElementById('theme-picker'),saved=localStorage.getItem('utube-mac-theme')||'ocean';document.body.dataset.theme=saved;p.value=saved;p.onchange=()=>{{document.body.dataset.theme=p.value;localStorage.setItem('utube-mac-theme',p.value)}}}})()</script></main></body></html>'''

def app_page(message=""):
    counts, free_space = library_stats()
    version = local_version(); version_folder = SHORTCUT_HISTORY / f"UTUBE MAC {version}"; note = next((item for item in version_folder.iterdir() if item.is_file() and item.name.lower().startswith("update note")), None) if version_folder.exists() else None
    version_card = f'<a class="card" href="/browse?target={urllib.parse.quote("version-UTUBE MAC " + version)}&path={urllib.parse.quote(note.name)}">{card("UTUBE MAC", "Bereit", "Lokale Version " + version + " · Versionsnotizen lesen")}</a>' if note else card("UTUBE MAC", "Bereit", "Lokale Version " + version)
    available = remote_update(); update_card = f'<section class="message"><b>Update verfügbar: {html.escape(available)}</b><br>Eine neue UTUBE-MAC-Version wartet auf dich. <form method="post" action="/action" style="display:inline"><input type="hidden" name="action" value="update"><button style="width:auto;margin:8px 0 0">Update jetzt prüfen</button></form></section>' if available else ""
    library_options = "".join(f'<option value="{html.escape(path, quote=True)}" {"selected" if path == str(DOWNLOADS) else ""}>{html.escape(path)}</option>' for path in library_locations())
    extension_state, extension_note = safari_extension_status()
    extension_card = f'<a class="card" href="/safari-extension">{card("Safari-Erweiterung", extension_state, extension_note)}</a>'
    content = f'''<section class="grid">{version_card}<a class="card" href="/library">{card("Mediathek", str(sum(counts.values())) + " Dateien", "MP4, MKV und MP3 abspielen und verwalten.")}</a><a class="card" href="/storage">{card("Freier Speicher", str(free_space) + " GB", "Größte Dateien und Speicheranalyse.")}</a>{extension_card}</section>{update_card}
<section class="panel"><h2>Deine Mediathek</h2><p class="sub">Aktuelle Dateien nach Format.</p><div class="chart">{library_chart()}</div></section>
<section class="panel"><h2>Neuer Download</h2><p class="sub">Wähle klar aus, ob du ein einzelnes Video oder eine Playlist laden möchtest. Die letzte Auswahl wird gespeichert.</p>
<form id="download-form" method="post" action="/action"><input type="hidden" name="action" value="download"><input id="url" name="url" placeholder="YouTube-Link einfügen" required autofocus onfocus="showSuggestions()"><div id="recommendations" class="folders" style="display:none;margin:-2px 0 12px"></div><div class="grid"><div><label class="label">Was möchtest du laden?</label><select id="mode" name="mode" onchange="updateControls()"><option value="single-mp4">Einzelnes Video – MP4</option><option value="playlist-mp4">Playlist – MP4</option><option value="single-mkv">Einzelnes Video – MKV</option><option value="playlist-mkv">Playlist – MKV</option><option value="single-mp3">Einzelnes Audio – MP3</option><option value="playlist-mp3">Playlist – MP3</option><option value="single-mp3-advanced">Einzelnes Audio – MP3 mit Metadaten</option><option value="playlist-mp3-advanced">Playlist – MP3 mit Metadaten</option></select></div><div id="quality-container"><label class="label">Videoqualität</label><select id="quality" name="quality"><option value="best">Beste verfügbare Qualität</option><option value="2160">Bis 4K</option><option value="1080">Bis 1080p</option><option value="720">Bis 720p</option><option value="480">Bis 480p</option></select></div><div><label class="label">Untertitel</label><input id="subtitles" name="subtitles" value="none" readonly><p class="hint">Für zuverlässige Downloads momentan ausgeschaltet.</p></div></div><p id="last-choice" class="hint"></p><label class="hint"><input id="cow-mode" type="checkbox"> Kuh-Fortschrittsfenster im Terminal verwenden</label><div class="actions"><button type="button" onclick="startDownload()">Download starten</button><button type="button" class="secondary" onclick="addToQueue()">Zur Warteschlange hinzufügen</button></div></form><div id="web-progress" class="progress-box"><b id="progress-title">Download wird vorbereitet …</b><p id="progress-phase" class="sub">Bitte einen Moment.</p><div class="bar-track"><div id="progress-fill" class="progress-fill" style="width:3%"></div></div><div class="progress-meta"><span id="progress-percent">0%</span><span id="progress-speed">—</span><span id="progress-eta">—</span></div></div><p class="hint">Klicke in das Linkfeld: offene YouTube-Videos erscheinen direkt als Vorschläge.</p></section>
<section class="panel"><h2>Warteschlange</h2><p class="sub">Sammle Downloads und starte sie anschließend nacheinander in einem Terminal-Fenster.</p><div id="queue" class="folders"></div><div class="actions"><button type="button" onclick="startQueue()">Warteschlange starten</button><button type="button" class="secondary" onclick="clearQueue()">Leeren</button></div></section>
<section class="panel"><h2>UTUBE MAC</h2><label class="label">Mediathek-Speicherort für die Einrichtung</label><select id="library-location">{library_options}</select><div class="actions"><button type="button" class="secondary" onclick="chooseLibrary()">Anderen Ordner auswählen</button><button type="button" class="secondary" onclick="removeLibrary()">Aus Liste entfernen</button><a class="folder" href="/open-shortcut">Kurzbefehl öffnen</a><form method="post" action="/action"><input type="hidden" name="action" value="folder"><button class="secondary">Download-Ordner öffnen</button></form><form method="post" action="/action" onsubmit="return confirm('Update-Prüfung starten?');"><input type="hidden" name="action" value="update"><button class="secondary">Update prüfen</button></form><button type="button" class="secondary" onclick="startSetup()">Einrichtung starten</button></div><p class="hint">Der ausgewählte Ordner wird gespeichert. Ein Shortcut mit bereits übergebenem Ordner fragt nicht erneut nach. „Aus Liste entfernen“ löscht keine Dateien.</p><div id="setup-progress" class="progress-box"><b id="setup-stage">Einrichtung wird gestartet …</b><p class="sub">Das Terminal bleibt für macOS- und Homebrew-Bestätigungen offen. Hier siehst du die verständliche Zusammenfassung.</p><div id="setup-lines" class="file-list"></div></div></section>'''
    chooser = '''<script>let queue=JSON.parse(localStorage.getItem('utube-mac-queue')||'[]'),progressTimer;function updateControls(){let audio=document.getElementById('mode').value.includes('mp3');document.getElementById('quality-container').style.display=audio?'none':''}function showProgress(job){let box=document.getElementById('web-progress');box.classList.add('show');clearInterval(progressTimer);progressTimer=setInterval(async()=>{try{let data=await fetch('/progress?job='+encodeURIComponent(job)).then(r=>r.json()),item=data[0];if(!item)return;let percent=parseFloat(item.PERCENT)||0;document.getElementById('progress-title').textContent=item.TITLE||'UTUBE MAC Download';document.getElementById('progress-phase').textContent=item.PHASE||'Download läuft';document.getElementById('progress-fill').style.width=Math.max(3,Math.min(100,percent))+'%';document.getElementById('progress-percent').textContent=Math.round(percent)+'%';document.getElementById('progress-speed').textContent=item.SPEED||'—';document.getElementById('progress-eta').textContent=item.ETA||'—';if(item.done){clearInterval(progressTimer);document.getElementById('progress-phase').textContent=item.RESULT==='completed'?'Fertig – deine Datei ist in der Mediathek.':(item.RESULT||'Download beendet.')}}catch(e){}},900)}async function startDownload(){let url=document.getElementById('url').value.trim();if(!url.startsWith('http')){alert('Bitte zuerst einen YouTube-Link auswählen oder einfügen.');return}if(document.getElementById('cow-mode').checked){if(confirm('Kuh-Fortschrittsfenster im Terminal starten?'))document.getElementById('download-form').submit();return}let body={url,mode:document.getElementById('mode').value,quality:document.getElementById('quality').value,subtitles:document.getElementById('subtitles').value};let response=await fetch('/download-background',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!response.ok){alert('Download konnte nicht gestartet werden.');return}let result=await response.json();showProgress(result.job)}function renderQueue(){let box=document.getElementById('queue');box.innerHTML=queue.length?'':'<p class="sub">Noch keine Downloads vorgemerkt.</p>';queue.forEach((item,index)=>{let b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=(item.mode.includes('playlist')?'Playlist':'Single')+' · '+item.mode.replace(/.*-/,'').toUpperCase()+'  ×';b.onclick=()=>{queue.splice(index,1);saveQueue()};box.appendChild(b)})}function saveQueue(){localStorage.setItem('utube-mac-queue',JSON.stringify(queue));renderQueue()}function addToQueue(){let url=document.getElementById('url').value.trim();if(!url.startsWith('http')){alert('Bitte zuerst einen YouTube-Link auswählen oder einfügen.');return}queue.push({url:url,mode:document.getElementById('mode').value,quality:document.getElementById('quality').value,subtitles:document.getElementById('subtitles').value});document.getElementById('url').value='';saveQueue()}function clearQueue(){queue=[];saveQueue()}async function startQueue(){if(!queue.length){alert('Die Warteschlange ist leer.');return}if(!confirm(queue.length+' Download(s) nacheinander im Terminal starten?'))return;let r=await fetch('/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(queue)});if(r.ok){clearQueue();alert('Die Warteschlange wurde im Terminal gestartet.')}else alert('Die Warteschlange konnte nicht gestartet werden.')}function thumbnail(url){let m=url.match(/[?&]v=([^&]+)/)||url.match(/youtu\\.be\\/([^?&/]+)/)||url.match(/shorts\\/([^?&/]+)/);return m?'https://i.ytimg.com/vi/'+m[1]+'/hqdefault.jpg':''}function kind(url){let m=url.match(/[?&]list=([^&]+)/);return m&&!m[1].startsWith('RD')?'Playlist':'Einzelnes Video'}async function showSuggestions(){let box=document.getElementById('recommendations');box.style.display='grid';box.innerHTML='<p class="sub">Offene YouTube-Videos werden geladen …</p>';try{let items=await fetch('/safari-tabs').then(r=>r.json());box.innerHTML='';if(!items.length)box.innerHTML='<p class="sub">Keine offenen YouTube-Videos gefunden.</p>';items.forEach(item=>{let b=document.createElement('button'),img=thumbnail(item.url);b.type='button';b.className='secondary';b.style.textAlign='left';b.style.padding='10px';b.innerHTML=(img?'<img src="'+img+'" style="width:96px;height:54px;object-fit:cover;border-radius:7px;vertical-align:middle;margin-right:9px">':'')+'<span><strong>'+kind(item.url)+'</strong><br>'+item.title.replace(/</g,'&lt;')+'</span>';b.onclick=()=>{document.getElementById('url').value=item.url;box.style.display='none'};box.appendChild(b)})}catch(e){box.innerHTML='<p class="sub">Safari konnte nicht abgefragt werden.</p>'}}updateControls();renderQueue()</script>'''
    setup_script = '''<script>let setupTimer;function startSetup(){if(!confirm('Einrichtung im Terminal starten? Die verständliche Übersicht bleibt hier sichtbar.'))return;fetch('/setup-web',{method:'POST'}).then(r=>{if(!r.ok)throw Error();document.getElementById('setup-progress').classList.add('show');clearInterval(setupTimer);setupTimer=setInterval(refreshSetup,1100);refreshSetup()}).catch(()=>alert('Einrichtung konnte nicht gestartet werden.'))}async function refreshSetup(){try{let data=await fetch('/setup-progress').then(r=>r.json()),lines=document.getElementById('setup-lines');document.getElementById('setup-stage').textContent=data.stage||'Einrichtung läuft';lines.innerHTML=(data.lines||[]).map(line=>'<div class="hint">'+line.replace(/</g,'&lt;')+'</div>').join('')||'<div class="hint">Warte auf die erste Rückmeldung aus der Einrichtung …</div>';if(data.done||data.failed){clearInterval(setupTimer);document.getElementById('setup-stage').textContent=data.done?'Einrichtung abgeschlossen.':'Einrichtung braucht Aufmerksamkeit im Terminal.'}}catch(e){}}document.addEventListener('DOMContentLoaded',()=>{let mode=document.getElementById('mode'),last=localStorage.getItem('utube-mac-last-mode');if(last&&[...mode.options].some(option=>option.value===last))mode.value=last;mode.addEventListener('change',()=>localStorage.setItem('utube-mac-last-mode',mode.value));updateControls();if(new URLSearchParams(location.search).get('setup')==='1'){document.getElementById('setup-progress').classList.add('show');clearInterval(setupTimer);setupTimer=setInterval(refreshSetup,1100);refreshSetup()}})</script>'''
    library_script = '''<script>async function chooseLibrary(){try{let r=await fetch('/choose-library',{method:'POST'});if(!r.ok)return;let d=await r.json();if(!d.path)return;let select=document.getElementById('library-location'),option=document.createElement('option');option.value=d.path;option.textContent=d.path;option.selected=true;select.appendChild(option)}catch(e){}}async function removeLibrary(){let select=document.getElementById('library-location'),path=select.value;if(!confirm('Diesen Ordner nur aus der gespeicherten Liste entfernen? Dateien bleiben erhalten.'))return;let r=await fetch('/remove-library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:path})});if(r.ok){select.options[select.selectedIndex].remove()}}let originalStartSetup=startSetup;startSetup=function(){let path=document.getElementById('library-location').value;if(!confirm('Einrichtung mit diesem Speicherort starten?\n'+path))return;fetch('/setup-web',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:path})}).then(r=>{if(!r.ok)throw Error();document.getElementById('setup-progress').classList.add('show');clearInterval(setupTimer);setupTimer=setInterval(refreshSetup,1100);refreshSetup()}).catch(()=>alert('Einrichtung konnte nicht gestartet werden.'))}</script>'''
    choice_script = '''<script>function rememberDownloadChoices(){let mode=document.getElementById('mode'),quality=document.getElementById('quality'),label=document.getElementById('last-choice');localStorage.setItem('utube-mac-last-mode',mode.value);localStorage.setItem('utube-mac-last-quality',quality.value);label.textContent='Gespeichert für den nächsten Download: '+mode.options[mode.selectedIndex].text+' · '+quality.options[quality.selectedIndex].text}document.addEventListener('DOMContentLoaded',()=>{let quality=document.getElementById('quality'),lastQuality=localStorage.getItem('utube-mac-last-quality');if(lastQuality&&[...quality.options].some(option=>option.value===lastQuality))quality.value=lastQuality;document.getElementById('mode').addEventListener('change',rememberDownloadChoices);quality.addEventListener('change',rememberDownloadChoices);rememberDownloadChoices()})</script>'''
    protected_json = json.dumps(sorted(PROTECTED_LIBRARIES))
    protection_script = f'''<script>const protectedLibraries=new Set({protected_json});function updateLibraryRemoveState(){{let select=document.getElementById('library-location'),button=document.querySelector('button[onclick="removeLibrary()"]');if(!select||!button)return;let protectedFolder=protectedLibraries.has(select.value);button.disabled=protectedFolder;button.title=protectedFolder?'Standard- und Apple-Music-Ordner bleiben immer verfügbar.':'Diesen gespeicherten Ordner aus der Liste entfernen';button.textContent=protectedFolder?'Geschützter Standardordner':'Aus Liste entfernen'}}document.addEventListener('DOMContentLoaded',()=>{{let select=document.getElementById('library-location');select.addEventListener('change',updateLibraryRemoveState);updateLibraryRemoveState()}})</script>'''
    return layout("UTUBE MAC", "Lokale Download-App. Die Dateien bleiben auf deinem Mac.", content + chooser + setup_script + library_script + choice_script + protection_script, message)

def developer_page(message=""):
    logs = sorted(LOGS.glob("setup-*.log"), reverse=True)[:8] if LOGS.exists() else []
    health_rows = "".join(f"<tr><td>{html.escape(name)}</td><td class={'ok' if status == 'Bereit' else 'bad'}>{html.escape(status)}</td></tr>" for name, status in health())
    log_rows = "".join(f'<li><a href="/browse?target=logs&path={urllib.parse.quote(log.name)}">{html.escape(log.name)} ansehen</a></li>' for log in logs) or "<li>Noch keine Setup-Berichte vorhanden.</li>"
    folders = [("UTUBE MAC – Application Support", "support"), ("Skripte", "scripts"), ("Einstellungen", "settings"), ("Gesamte Historie", "history"), ("Setup-Berichte", "logs"), ("Skript-Historie", "script-history"), ("Shortcut-Versionen", "shortcut-history"), ("Safari-Erweiterung", "safari-extension"), ("GitHub-Repository", "repository"), ("Laufzeit und Download-Fortschritt", "runtime"), ("Temporäre Dateien", "temp"), ("Developer Dashboard", "dashboard")]
    folder_buttons = "".join(f'<a class="folder" href="/browse?target={urllib.parse.quote(key)}">{html.escape(label)}</a>' for label, key in folders if open_targets().get(key, Path()).exists())
    shortcut_versions = sorted((p for p in SHORTCUT_HISTORY.iterdir() if p.is_dir()), key=lambda p: p.name) if SHORTCUT_HISTORY.exists() else []
    script_versions = sorted((p for p in SCRIPT_HISTORY.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:10] if SCRIPT_HISTORY.exists() else []
    shortcut_version_buttons = "".join(f'<a class="folder" href="/browse?target={urllib.parse.quote("version-" + p.name)}">{html.escape(p.name)}</a>' for p in shortcut_versions) or '<p class="sub">Keine Shortcut-Versionen vorhanden.</p>'
    script_version_buttons = "".join(f'<a class="folder" href="/browse?target={urllib.parse.quote("version-" + p.name)}">{html.escape(p.name)}</a>' for p in script_versions) or '<p class="sub">Noch keine Skript-Sicherungen vorhanden.</p>'
    counts, free_space = library_stats()
    content = f'''<section class="grid">{card("Lokale Version", local_version())}{card("yt-dlp", tool_version("yt-dlp", "--version"))}{card("FFmpeg", tool_version("ffmpeg", "-version"))}{card("Beets", tool_version("beet", "--version"))}</section>
<section class="panel"><h2>Download-Übersicht</h2><p class="sub">{sum(counts.values())} Mediendateien · {free_space} GB frei</p><div class="chart">{library_chart()}</div></section>
<section class="panel"><h2>Wartung</h2><div class="actions"><form method="post" action="/action"><input type="hidden" name="action" value="setup"><button>Einrichtung starten</button></form><form method="post" action="/action"><input type="hidden" name="action" value="update"><button>Update prüfen</button></form><form method="post" action="/action"><input type="hidden" name="action" value="health"><button class="secondary">Skript-Check</button></form><form method="post" action="/action"><input type="hidden" name="action" value="folder"><button class="secondary">Download-Ordner öffnen</button></form></div></section>
<section class="panel"><h2>Dateizentrale</h2><p class="sub">Öffnet Dateien direkt in UTUBE MAC oder im Finder.</p><div class="folders">{folder_buttons}</div><p><a class="folder" href="/safari-extension">Safari-Erweiterung einrichten</a></p></section>
<section class="panel"><h2>Shortcut-Versionen</h2><p class="sub">Gespeicherte Versionen des Kurzbefehls.</p><div class="folders">{shortcut_version_buttons}</div></section>
<section class="panel"><h2>Skript-Sicherungen</h2><p class="sub">Die letzten zehn Sicherungen der UTUBE-MAC-Skripte und Oberflächen.</p><div class="folders">{script_version_buttons}</div></section>
<section class="panel"><h2>Helferskripte</h2><table><tr><td>Installationsskript</td><td>Einrichtung und Kern-Tools</td></tr><tr><td>Downloader</td><td>Video-, Playlist- und MP3-Downloads</td></tr><tr><td>Updater</td><td>GitHub-Version und Tool-Updates</td></tr>{health_rows}</table></section>
<section class="panel"><h2>Letzte Setup-Berichte</h2><ul>{log_rows}</ul></section>'''
    return layout("UTUBE MAC – Developer Console", "Lokale Test- und Diagnosezentrale. Aktionen starten nur definierte UTUBE-MAC-Skripte.", content, message)

class Handler(BaseHTTPRequestHandler):
    def send_page(self, page):
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(page.encode())
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/safari-extension":
            self.send_page(safari_extension_guide_page()); return
        if parsed.path == "/install-safari-extension":
            app = Path("/Applications/UTUBE MAC Safari Extension 6.2.0.app")
            if app.exists(): subprocess.Popen(["open", str(app)])
            self.send_response(303); self.send_header("Location", "/safari-extension"); self.end_headers(); return
        if parsed.path == "/open-shortcut":
            subprocess.Popen(["open", "shortcuts://open-shortcut?name=UTUBE%20MAC"])
            self.send_response(303); self.send_header("Location", "/"); self.end_headers(); return
        if parsed.path in {"/library", "/storage"}:
            chosen = urllib.parse.parse_qs(parsed.query).get("filter", ["ALL"])[0]
            self.send_page(library_page(chosen) if parsed.path == "/library" else storage_page()); return
        if parsed.path == "/media":
            path = safe_media(urllib.parse.parse_qs(parsed.query).get("path", [""])[0])
            if not path: self.send_error(404); return
            size = path.stat().st_size; start = 0; end = size - 1
            requested = self.headers.get("Range", "")
            if requested.startswith("bytes="):
                try:
                    first, last = requested[6:].split("-", 1); start = int(first) if first else 0; end = int(last) if last else end
                    if start < 0 or start >= size or end < start: raise ValueError
                    end = min(end, size - 1)
                    self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                except ValueError:
                    self.send_error(416); return
            else: self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream"); self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
            with path.open("rb") as source:
                source.seek(start); remaining = end - start + 1
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block: break
                    self.wfile.write(block); remaining -= len(block)
            return
        if parsed.path == "/reveal":
            path = safe_media(urllib.parse.parse_qs(parsed.query).get("path", [""])[0])
            if path: subprocess.Popen(["open", "-R", str(path)])
            self.send_response(303); self.send_header("Location", "/library"); self.end_headers(); return
        if parsed.path == "/open":
            target = urllib.parse.parse_qs(parsed.query).get("target", [""])[0]
            path = open_targets().get(target)
            if path and path.exists(): subprocess.Popen(["open", str(path)])
            self.send_response(303); self.send_header("Location", "/developer"); self.end_headers(); return
        if parsed.path == "/browse":
            query = urllib.parse.parse_qs(parsed.query)
            self.send_page(file_browser_page(query.get("target", [""])[0], query.get("path", [""])[0])); return
        if parsed.path in {"/reveal-file", "/launch-file"}:
            query = urllib.parse.parse_qs(parsed.query); path = safe_target_item(query.get("target", [""])[0], query.get("path", [""])[0])
            if path:
                subprocess.Popen(["open", "-R", str(path)] if parsed.path == "/reveal-file" else ["open", str(path)])
            self.send_response(303); self.send_header("Location", "/developer"); self.end_headers(); return
        if parsed.path == "/progress":
            requested = urllib.parse.parse_qs(parsed.query).get("job", [""])[0]
            payload = [item for item in progress_jobs() if not requested or item["id"] == requested]
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(json.dumps(payload).encode()); return
        if parsed.path == "/setup-progress":
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(json.dumps(setup_progress()).encode()); return
        if self.path.startswith("/safari-tabs"):
            payload = json.dumps(safari_youtube_tabs()).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(payload); return
        message = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("message", [""])[0]
        self.send_page(developer_page(message) if self.path.startswith("/developer") else app_page(message))
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0")); raw = self.rfile.read(length).decode()
        if self.path == "/extension-heartbeat":
            heartbeat = RUNTIME / "Safari Extension Heartbeat.json"; heartbeat.parent.mkdir(parents=True, exist_ok=True)
            heartbeat.write_text(json.dumps({"seen": int(time.time())}))
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{"active":true}'); return
        if self.path == "/setup-web":
            try: requested = json.loads(raw).get("path", "") if raw else ""
            except Exception: requested = ""
            selected = Path(requested).expanduser() if requested else DOWNLOADS
            if INSTALLER.exists():
                selected.mkdir(parents=True, exist_ok=True)
                remember_library(selected)
                run_in_terminal([INSTALLER, "", "", "", str(selected)])
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{"started":true}')
            else: self.send_error(404)
            return
        if self.path == "/choose-library":
            selected = choose_library_folder()
            if selected: remember_library(selected)
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(json.dumps({"path": selected}).encode()); return
        if self.path == "/remove-library":
            try: selected = json.loads(raw).get("path", "")
            except Exception: selected = ""
            if selected and selected != str(DOWNLOADS): forget_library(selected)
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{}'); return
        if self.path == "/download-background":
            try: item = json.loads(raw)
            except Exception: item = {}
            allowed = {"auto-mp4", "auto-mkv", "auto-mp3", "auto-mp3-advanced", "single-mp4", "playlist-mp4", "single-mkv", "playlist-mkv", "single-mp3", "playlist-mp3", "single-mp3-advanced", "playlist-mp3-advanced"}
            valid = isinstance(item, dict) and item.get("mode") in allowed and item.get("quality") in {"best", "fast", "2160", "1080", "720", "480"} and item.get("subtitles") in {"none", "de", "en", "all"} and str(item.get("url", "")).startswith(("https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/"))
            if valid and DOWNLOADER.exists():
                job = run_download_in_background(item["mode"], item["url"], item["quality"], item["subtitles"])
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(json.dumps({"job": job}).encode())
            else: self.send_error(400)
            return
        if self.path == "/extension-queue":
            try: item = json.loads(raw)
            except Exception: item = {}
            url = str(item.get("url", ""))
            if url.startswith(("https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/")):
                queue_file = RUNTIME / "Safari Extension Queue.json"; queue_file.parent.mkdir(parents=True, exist_ok=True)
                try: items = json.loads(queue_file.read_text())
                except Exception: items = []
                items.append({"url": url, "title": str(item.get("title", "YouTube")), "added": int(time.time())})
                queue_file.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=2))
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{"queued":true}'); return
            self.send_error(400); return
        if self.path == "/queue":
            try:
                items = json.loads(raw)
            except Exception:
                items = []
            allowed = {"auto-mp4", "auto-mkv", "auto-mp3", "auto-mp3-advanced", "single-mp4", "playlist-mp4", "single-mkv", "playlist-mkv", "single-mp3", "playlist-mp3", "single-mp3-advanced", "playlist-mp3-advanced"}
            valid = isinstance(items, list) and 0 < len(items) <= 20 and all(isinstance(item, dict) and item.get("mode") in allowed and item.get("quality") in {"best", "fast", "2160", "1080", "720", "480"} and item.get("subtitles") in {"none", "de", "en", "all"} and str(item.get("url", "")).startswith(("https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/")) for item in items)
            if valid and DOWNLOADER.exists(): run_queue_in_terminal(items); status = 200
            else: status = 400
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{}'); return
        data = urllib.parse.parse_qs(raw)
        action = data.get("action", [""])[0]; message = "Aktion nicht erkannt."
        destination = "/developer" if self.headers.get("Referer", "").split("?")[0].endswith("/developer") else "/"
        if action == "setup" and INSTALLER.exists(): run_in_terminal([INSTALLER]); message = "Die Einrichtung wurde im Terminal gestartet."
        elif action == "update" and UPDATER.exists(): run_silently(UPDATER); message = "Die Update-Prüfung läuft im Hintergrund. Das Ergebnis erscheint als UTUBE-MAC-Mitteilung."
        elif action == "folder": subprocess.Popen(["open", str(DOWNLOADS)]); message = "Der Download-Ordner wurde geöffnet."
        elif action == "health": message = "Der Skript-Check wurde aktualisiert."
        elif action == "trash":
            path = safe_media(data.get("path", [""])[0])
            if path:
                applescript = 'on run argv\ntell application "Finder" to delete (POSIX file (item 1 of argv))\nend run'
                result = subprocess.run(["osascript", "-e", applescript, str(path)], capture_output=True, text=True, timeout=12)
                message = "Die Datei wurde in den Papierkorb gelegt." if result.returncode == 0 else "Die Datei konnte nicht in den Papierkorb gelegt werden."
            else: message = "Diese Datei ist nicht mehr im UTUBE-MAC-Download-Ordner vorhanden."
            destination = "/storage" if self.headers.get("Referer", "").split("?")[0].endswith("/storage") else "/library"
        elif action == "download":
            url = data.get("url", [""])[0].strip(); mode = data.get("mode", ["auto-mp4"])[0]; quality = data.get("quality", ["best"])[0]; subtitles = data.get("subtitles", ["none"])[0]
            allowed = {"auto-mp4", "auto-mkv", "auto-mp3", "auto-mp3-advanced", "single-mp4", "playlist-mp4", "single-mkv", "playlist-mkv", "single-mp3", "playlist-mp3", "single-mp3-advanced", "playlist-mp3-advanced"}; qualities = {"best", "fast", "2160", "1080", "720", "480"}; subtitle_modes = {"none", "de", "en", "all"}
            if url.startswith(("https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/")) and DOWNLOADER.exists() and mode in allowed and quality in qualities and subtitles in subtitle_modes:
                run_in_terminal([DOWNLOADER, mode, url, quality, subtitles]); message = "Der Download wurde im Terminal gestartet."
            else: message = "Bitte einen gültigen YouTube-Link einfügen."
        self.send_response(303); self.send_header("Location", destination + "?message=" + urllib.parse.quote(message)); self.end_headers()
    def log_message(self, *args): pass

if __name__ == "__main__": ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
