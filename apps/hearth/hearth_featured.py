"""Download and install stories from Hearth's hosted featured catalog."""
import json

from hearth_core import HearthError, MAX_SOURCE
from hearth_storage import error_text


MANIFEST_URL = "https://www.heyvictorfrost.com/hearth/stories/manifest.json"
STORIES_URL = "https://www.heyvictorfrost.com/hearth/stories/"
MAX_MANIFEST = 32768
MAX_DOWNLOAD = 262144


def read_catalog(http):
    response = http.get(MANIFEST_URL, {"Accept": "application/json"}, 12000, MAX_MANIFEST, True)
    status = response.get("status_code", 0)
    if status < 200 or status >= 300:
        raise HearthError("Featured catalog returned HTTP %s" % status)
    if response.get("truncated"):
        raise HearthError("Featured catalog is too large")
    try:
        body = response.get("body", b"").decode("utf-8")
        manifest = json.loads(body)
    except (AttributeError, UnicodeError, ValueError):
        raise HearthError("Featured catalog is not valid UTF-8 JSON")
    stories = manifest.get("stories") if isinstance(manifest, dict) else None
    if not isinstance(stories, list) or len(stories) > 64:
        raise HearthError("Featured catalog has an invalid stories list")

    safe = []
    for entry in stories:
        if not isinstance(entry, dict):
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or not filename.endswith(".hearth"):
            continue
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in filename):
            continue
        if filename.startswith("."):
            continue
        title = entry.get("title")
        game_id = entry.get("id")
        author = entry.get("author", "Hearth Collection")
        description = entry.get("description", "")
        minutes = entry.get("minutes", 0)
        if not isinstance(title, str) or not title or len(title) > 100:
            continue
        if not isinstance(game_id, str) or not game_id or len(game_id) > 160:
            continue
        if not isinstance(author, str): author = "Hearth Collection"
        if not isinstance(description, str): description = ""
        if type(minutes) not in (int, float): minutes = 0
        safe.append({"id": game_id, "file": filename, "title": title,
                     "author": author, "description": description, "minutes": minutes})
    return safe


def download_story(http, store, entry):
    response = http.get(STORIES_URL + entry["file"], None, 20000, MAX_DOWNLOAD, True)
    status = response.get("status_code", 0)
    if status < 200 or status >= 300:
        raise HearthError("Story download returned HTTP %s" % status)
    if response.get("truncated"):
        raise HearthError("Downloaded story exceeds the size limit")
    body = response.get("body", b"")
    try:
        source = body.decode("utf-8")
    except (AttributeError, UnicodeError):
        raise HearthError("Downloaded story is not valid UTF-8")
    del body, response
    if len(source) > MAX_SOURCE:
        raise HearthError("Downloaded story exceeds the size limit")
    return store.import_text(source, entry["id"])


def featured_menu(view, store, solaros):
    """Poll the hosted manifest each time the player opens this submenu."""
    while not view.closing():
        try:
            entries = read_catalog(solaros.http)
        except Exception as error:
            view.message("Featured stories unavailable", error_text(error))
            return

        labels = []
        for entry in entries:
            length = (" · %s min" % entry["minutes"]) if entry["minutes"] else ""
            labels.append(entry["title"] + " — " + entry["author"] + length)
        labels.extend(["Refresh featured list", "Back"])
        selected = view.menu("Featured stories", labels)
        if selected is None or selected == len(entries) + 1:
            return
        if selected == len(entries):
            continue

        entry = entries[selected]
        details = entry["description"]
        if details:
            details += "\n\n"
        duration = ("%s min" % entry["minutes"]) if entry["minutes"] else "time unknown"
        details += "%s · %s" % (entry["author"], duration)
        view.message(entry["title"], details)
        action = view.menu(entry["title"], ["Download to Hearth library", "Back"])
        if action != 0:
            continue
        try:
            title = download_story(solaros.http, store, entry)
            view.message("Story added", title + " is now in your Hearth library.")
        except Exception as error:
            message = error_text(error)
            if "already installed" in message.lower():
                view.message("Already in library", entry["title"] + " is already installed.")
            else:
                view.message("Download unavailable", message)
