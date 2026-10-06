"""Host-owned library and save storage. No path is taken from story commands."""
import gc
import json
import sys
from hearth_core import Engine, Story, HearthError, MAX_SOURCE, checksum

MAX_SAVE = 2097152
SLOTS = 5


def text_open(path, mode="r"):
    if sys.platform == "solaros":
        return open(path, mode)
    return open(path, mode, encoding="utf-8")


def read_limited(source, limit, chunk_size=4096):
    """Read at most limit characters, avoiding a chunks-plus-join peak."""
    result, length = "", 0
    while True:
        chunk = source.read(min(chunk_size, limit + 1 - length))
        if not chunk:
            return result
        length += len(chunk)
        if length > limit:
            raise HearthError("Story source exceeds the size limit")
        result += chunk


def game_field_from_file(path, field):
    """Read one GAME field without parsing the story's scenes."""
    with text_open(path, "r") as source:
        section = False
        for raw in source:
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent == 0:
                section = text == "GAME"
                continue
            if section and text.split(":", 1)[0].strip().lower() == field.lower() and ":" in text:
                value = text.split(":", 1)[1].strip()
                try:
                    return json.loads(value)
                except ValueError:
                    return None
    return None


def game_id_from_file(path):
    """Read an installed story ID without compiling its scenes."""
    return game_field_from_file(path, "ID")


def error_text(error):
    """Format terse MicroPython exceptions without calling their __str__."""
    args = getattr(error, "args", ())
    if args:
        return " ".join("%s" % value for value in args)
    return error.__class__.__name__


def missing_error(error):
    """SolarOS bindings expose ESP names; desktop Python exposes errno."""
    args = getattr(error, "args", ())
    if not args:
        return False
    value = args[0]
    return value == 2 or value == "ESP_ERR_NOT_FOUND" or "NOT_FOUND" in (value if isinstance(value, str) else "")


class Store:
    def __init__(self, root, fs):
        self.root, self.fs = root, fs

    def exists(self, path):
        try:
            with text_open(path, "r") as f:
                return True
        except OSError as error:
            if missing_error(error):
                return False
            raise

    def mkdir(self, path):
        try:
            self.fs.mkdir(path)
        except OSError as error:
            if sys.platform != "solaros" and (not error.args or error.args[0] != 17):
                raise

    def remove(self, path):
        if self.exists(path):
            try:
                self.fs.remove(path)
            except OSError:
                pass

    def write(self, path, data):
        temp, backup = path + ".tmp", path + ".bak"
        
        # Free memory before serializing
        gc.collect()
        
        with text_open(temp, "w") as output:
            json.dump(data, output)
            output.flush()
            
        had_primary = self.exists(path)
        if had_primary:
            self.remove(backup)
            try:
                self.fs.rename(path, backup)
            except OSError:
                pass
                
        try:
            self.fs.rename(temp, path)
        except Exception:
            if had_primary:
                try:
                    self.fs.rename(backup, path)
                except OSError:
                    pass
            raise
        finally:
            gc.collect()

    def read(self, path, limit=MAX_SAVE):
        gc.collect()
        try:
            with text_open(path, "r") as source:
                data = json.load(source)
            gc.collect()
            return data
        except ValueError:
            raise HearthError("Invalid JSON file")

    def story(self, filename):
        if not filename.endswith(".hearth") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in filename) or filename.startswith("."):
            raise HearthError("Invalid library filename")
        
        gc.collect()
        with text_open(self.root + "/" + filename, "r") as source:
            story_obj = Story(source)
        gc.collect()
        return story_obj

    def title(self, filename):
        if not filename.endswith(".hearth") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in filename) or filename.startswith("."):
            raise HearthError("Invalid library filename")
        title = game_field_from_file(self.root + "/" + filename, "Title")
        if not isinstance(title, str) or not title:
            raise HearthError("Story has no valid title")
        return title

    def library(self):
        path = self.root + "/library.json"
        for candidate in (path, path + ".tmp", path + ".bak"):
            if self.exists(candidate):
                try:
                    files = self.read(candidate, 16384)
                    if not isinstance(files, list) or len(files) > 64 or not all(isinstance(f, str) for f in files):
                        raise HearthError("Invalid library index")
                    return files
                except HearthError:
                    continue
        if any(self.exists(p) for p in (path, path + ".tmp", path + ".bak")):
            raise HearthError("Library index is damaged; files were left unchanged")
        return ["welcome_to_hearth.hearth"]

    def import_story(self, source_path):
        """Stage a local story on disk so compilation does not overlap source text."""
        gc.collect()
        temp = self.root + "/.importing.hearth"
        try:
            total = 0
            with text_open(source_path, "r") as source:
                with text_open(temp, "w") as output:
                    while True:
                        chunk = source.read(min(4096, MAX_SOURCE + 1 - total))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_SOURCE:
                            raise HearthError("Story source exceeds the size limit")
                        output.write(chunk)
                    output.flush()
            return self._install_staged(temp)
        finally:
            self.remove(temp)
            gc.collect()

    def _install_staged(self, staged, expected_id=None):
        gc.collect()
        with text_open(staged, "r") as source:
            story = Story(source)
        if expected_id is not None and story.meta["id"] != expected_id:
            raise HearthError("The downloaded story ID does not match its catalog entry")
        title = story.meta["title"]
        files = self.library()
        for filename in files:
            if game_id_from_file(self.root + "/" + filename) == story.meta["id"]:
                raise HearthError("A game with this ID is already installed")
        if len(files) >= 64:
            raise HearthError("Library limit is 64 adventures")
        filename = checksum(story.meta["id"]) + ".hearth"
        destination = self.root + "/" + filename
        self.fs.rename(staged, destination)
        del story
        gc.collect()
        try:
            self.write(self.root + "/library.json", files + [filename])
        except Exception:
            self.fs.remove(destination)
            raise
        return title

    def import_text(self, text, expected_id=None):
        """Stage provided story text, then validate and install it from disk."""
        if not isinstance(text, str) or len(text) > MAX_SOURCE:
            raise HearthError("Story source exceeds the size limit")
        temp = self.root + "/.importing.hearth"
        try:
            with text_open(temp, "w") as output:
                output.write(text)
                output.flush()
            del text
            gc.collect()
            return self._install_staged(temp, expected_id)
        finally:
            self.remove(temp)
            gc.collect()

    def slot_path(self, story, slot, create=False):
        if type(slot) is not int or not 1 <= slot <= SLOTS:
            raise HearthError("Save slot must be 1 through 5")
        base = self.root + "/saves"
        folder = base + "/" + checksum(story.meta["id"])
        if create:
            self.mkdir(base)
            self.mkdir(folder)
        return folder + "/%s.json" % slot

    def save(self, engine, slot, timestamp):
        gc.collect()
        snapshot = engine.snapshot(timestamp)
        self.write(self.slot_path(engine.story, slot, True), snapshot)
        del snapshot
        gc.collect()

    def load(self, story, slot):
        path = self.slot_path(story, slot)
        failures = []
        for candidate in (path, path + ".tmp", path + ".bak"):
            if self.exists(candidate):
                try:
                    gc.collect()
                    save_data = self.read(candidate)
                    engine = Engine.restore(story, save_data)
                    del save_data
                    gc.collect()
                    return engine, ("Recovered a complete save generation." if candidate != path else "Loaded.")
                except HearthError as error:
                    message = error_text(error)
                    if "incompatible" in message: raise
                    failures.append(message)
        raise HearthError(failures[0] if failures else "This slot is empty")

    def slots(self, story):
        result = []
        for slot in range(1, SLOTS + 1):
            path = self.slot_path(story, slot)
            if not any(self.exists(p) for p in (path, path + ".tmp", path + ".bak")):
                result.append("Empty")
                continue
            try:
                engine, note = self.load(story, slot)
                stamp = str(engine.saved_at)
                result.append(stamp + " — " + engine.scene + (" (recovered)" if note.startswith("Recovered") else ""))
                del engine
                gc.collect()
            except HearthError as error:
                result.append(error_text(error))
        return result

    def delete(self, story, slot):
        path = self.slot_path(story, slot)
        for candidate in (path, path + ".tmp", path + ".bak"):
            self.remove(candidate)
        gc.collect()

    def delete_story(self, filename, story):
        """Remove one installed story, its index entry, and all of its saves."""
        if not isinstance(filename, str) or not filename.endswith(".hearth") or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in filename) or filename.startswith("."):
            raise HearthError("Invalid library filename")
        files = self.library()
        if filename not in files:
            raise HearthError("This adventure is no longer in the library")
        if filename != "welcome_to_hearth.hearth" and filename != checksum(story.meta["id"]) + ".hearth":
            raise HearthError("The selected adventure does not match its library file")

        index_path = self.root + "/library.json"
        self.write(index_path, [item for item in files if item != filename])

        failures = []
        candidates = [self.root + "/" + filename, index_path + ".bak", index_path + ".tmp"]
        save_base = self.root + "/saves/" + checksum(story.meta["id"])
        for slot in range(1, SLOTS + 1):
            path = save_base + "/%s.json" % slot
            candidates.extend((path, path + ".tmp", path + ".bak"))
        for path in candidates:
            try:
                if self.exists(path):
                    self.fs.remove(path)
            except OSError as error:
                if not missing_error(error): failures.append(path)
        gc.collect()
        if failures:
            names = ", ".join(path.rsplit("/", 1)[-1] for path in failures)
            raise HearthError("Adventure removed from the library, but these stored files could not be deleted: " + names)
