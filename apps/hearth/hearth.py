"""Hearth entry point: SolarOS player, desktop console, and author validation."""
import sys
from hearth_core import Engine, HearthError, Story, MAX_SOURCE
from hearth_featured import featured_menu
from hearth_storage import Store, SLOTS, error_text, text_open, read_limited
from hearth_view import SolarView, follow_choice, layout, plain, reading_top, styled_chars


def app_directory():
    path = globals().get("__file__", sys.argv[0]).replace("\\", "/")
    position = path.rfind("/")
    return path[:position] if position > 0 else "/" if position == 0 else "."


def timestamp(solaros=None):
    if solaros:
        date = solaros.time.datetime()
        return "%04d-%02d-%02d %02d:%02d:%02d" % tuple(date[k] for k in ("year", "month", "day", "hour", "minute", "second")) + (" (clock unverified)" if not date.get("clock_integrity") else "")
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


def save_menu(view, store, story, engine=None, mode="load"):
    while not view.closing():
        labels = store.slots(story)
        heading = {"save": "Save game", "load": "Load game", "delete": "Delete save"}.get(mode, "Save slots")
        slot = view.menu(heading, ["%s. %s" % (i + 1, label) for i, label in enumerate(labels)])
        if slot is None: return None
        slot += 1
        try:
            if mode == "save":
                if labels[slot - 1] != "Empty" and view.menu("Replace slot %s?" % slot, ["Cancel", "Replace save"]) != 1:
                    continue
                store.save(engine, slot, timestamp(view.solaros))
                view.message("Saved", "Progress saved in slot %s." % slot)
                return None
            if mode == "delete":
                if view.menu("Delete slot %s?" % slot, ["Cancel", "Delete save"]) == 1:
                    store.delete(story, slot)
                continue
            restored, note = store.load(story, slot)
            if note.startswith("Recovered"): view.message("Save recovered", note)
            return restored
        except (HearthError, OSError) as error:
            view.message("Save unavailable", error_text(error))


def play(view, store, engine):
    selected, top, changed, restored = 0, 0, True, True
    rows, choices, last = [], [], 0
    layout_cache = {}
    dirty = True
    while not view.closing():
        if engine.phase == "input":
            response = view.input_text(engine.story.meta["title"], engine.pending_input["prompt"], engine.pending_input["type"])
            if response is None:
                action = view.menu("Input paused", ["Continue entering response", "Save game", "Load game", "Return to library"])
                if action == 1: save_menu(view, store, engine.story, engine, "save")
                elif action == 2:
                    loaded = save_menu(view, store, engine.story)
                    if loaded: engine, changed = loaded, True
                elif action == 3: return
                continue
            try:
                engine.submit_input(response)
                changed = True
            except HearthError as error:
                view.message("Invalid response", error_text(error))
                changed = True
            continue
        if changed:
            view.measure()
            rows, last, choices = layout(engine, view.cols, layout_cache)
            selected = 0
            top = reading_top(rows, choices, engine.phase, view.rows, last)
            changed, restored, dirty = False, False, True
        if dirty:
            footer = "Enter choose" if engine.phase == "choice" else "Enter library" if engine.phase == "ended" else "Enter next"
            footer += " S save L load PgUp/Dn scroll Esc menu"
            view.frame(engine.story.meta["title"], rows, top, selected if engine.phase == "choice" else -1, footer)
            dirty = False
        key = view.key(250)
        if key is None: continue
        if key in (ord("s"), ord("S")):
            dirty = True
            save_menu(view, store, engine.story, engine, "save")
        elif key in (ord("l"), ord("L")):
            dirty = True
            loaded = save_menu(view, store, engine.story)
            if loaded:
                engine, changed, restored = loaded, True, True
                import gc
                gc.collect()  # Purge old engine state
        elif view.iskey(key, "ESCAPE"):
            dirty = True
            action = view.menu("Adventure paused", ["Continue", "Save game", "Load game", "Return to library (unsaved progress is lost)"])
            if action == 1: save_menu(view, store, engine.story, engine, "save")
            elif action == 2:
                loaded = save_menu(view, store, engine.story)
                if loaded: engine, changed, restored = loaded, True, True
            elif action == 3: return
        elif view.iskey(key, "PAGE_UP"):
            new_top = max(0, top - view.rows)
            if new_top != top: top, dirty = new_top, True
        elif view.iskey(key, "PAGE_DOWN"):
            new_top = min(max(0, len(rows) - view.rows), top + view.rows)
            if new_top != top: top, dirty = new_top, True
        elif engine.phase == "choice" and (view.iskey(key, "UP") or view.iskey(key, "DOWN")):
            new_selected = max(0, min(len(choices) - 1, selected + (1 if view.iskey(key, "DOWN") else -1)))
            if new_selected != selected:
                selected = new_selected
                top = follow_choice(rows, choices, selected, top, view.rows)
                dirty = True
        elif key in (10, 13, 32):
            if engine.phase == "ended": return
            if engine.phase == "text":
                if top + view.rows < len(rows):
                    top += view.rows
                    dirty = True
                else:
                    engine.advance()
                    changed = True
            elif engine.options[selected]["enabled"]:
                engine.choose(engine.options[selected]["index"])
                changed = True


def solar_main(solaros, store):
    view = SolarView(solaros)
    try:
        while not view.closing():
            files, titles = store.library(), []
            for filename in files:
                try:
                    titles.append(store.title(filename))
                except (HearthError, OSError) as error:
                    titles.append(filename + " — unavailable")
            index = view.menu("Hearth | Adventures", titles + ["Featured stories", "Import instructions"])
            if index is None: return
            if index == len(files):
                featured_menu(view, store, solaros)
                continue
            if index == len(files) + 1:
                view.message("Add an adventure", "From the SolarOS shell, run:\npython /apps/hearth/hearth.py --import /path/story.hearth\n\nHearth validates and copies the story into its library. Story commands never access files.")
                continue
            try:
                story = store.story(files[index])
                while not view.closing():
                    action = view.menu(story.meta["title"], ["New game", "Load game", "About this adventure", "Delete a save", "Delete this adventure"])
                    if action is None: break
                    if action == 0:
                        view.message(story.meta["title"], story.meta["description"] + "\n\nContent warnings: " + (story.meta["contentwarnings"] or "None listed"))
                        if not view.closing(): play(view, store, Engine(story))
                    elif action == 1:
                        engine = save_menu(view, store, story)
                        if engine: play(view, store, engine)
                    elif action == 2:
                        view.message(story.meta["title"], "\n".join("%s: %s" % (k, story.meta[k]) for k in ("author", "revision", "genre", "estimatedminutes", "description", "contentwarnings")))
                    elif action == 3:
                        save_menu(view, store, story, mode="delete")
                    elif action == 4:
                        confirm = view.menu("Delete %s?" % story.meta["title"], ["Cancel", "Delete adventure and saves"])
                        if confirm == 1:
                            store.delete_story(files[index], story)
                            view.message("Adventure deleted", story.meta["title"] + " and its saved games were removed from Hearth.")
                            break
            except (HearthError, OSError) as error:
                view.message("Adventure error", error_text(error))
    finally:
        import gc
        # Release story/compiler structures before gfx.end() asks the shell to
        # rebuild its terminal framebuffer on memory-constrained devices.
        files = titles = story = engine = None
        gc.collect()
        view.close()
        gc.collect()

def console(store):
    """Desktop author preview; uses the same engine and save files."""
    while True:
        files = store.library()
        print("\nHEARTH\n")
        for i, filename in enumerate(files):
            try: print("%s. %s" % (i + 1, store.story(filename).meta["title"]))
            except HearthError as error: print("%s. %s (%s)" % (i + 1, filename, error))
        value = input("Adventure number, d N delete, or q: ").strip()
        if value.lower() == "q": return
        if value.lower().startswith("d "):
            try:
                index = int(value[2:]) - 1
                if index < 0 or index >= len(files): raise HearthError("Unknown adventure")
                story = store.story(files[index])
                print("Delete %s and all its saved games? This cannot be undone." % story.meta["title"])
                if input("Type y to confirm: ").strip().lower() == "y":
                    store.delete_story(files[index], story)
                    print("Adventure deleted.")
            except (HearthError, OSError, ValueError) as error:
                print(error_text(error))
            continue
        try:
            index = int(value) - 1
            if index < 0 or index >= len(files): raise HearthError("Unknown adventure")
            story = store.story(files[index])
            print(story.meta["description"])
            print("Content warnings: " + (story.meta["contentwarnings"] or "None listed"))
            engine = Engine(story)
            while True:
                if engine.transcript:
                    print("\n" + "".join(c[0] for c in styled_chars(engine.transcript[-1])))
                if engine.phase == "choice":
                    for o in engine.options:
                        print("%s. %s%s" % (o["index"] + 1, plain(o["display"]), "" if o["enabled"] else " [" + (plain(o["reason"]) if o["reason"] else "Unavailable") + "]"))
                if engine.phase == "input": print(engine.pending_input["prompt"])
                if engine.phase == "ended": print("The end.")
                answer = input("Enter/choice; s N save, l N load, d N delete, slots, q library: ").strip()
                if answer.lower() == "q": break
                try:
                    if answer == "slots":
                        for i, label in enumerate(store.slots(story)): print("%s: %s" % (i + 1, label))
                    elif answer.startswith("s "):
                        slot = int(answer[2:])
                        if not 1 <= slot <= SLOTS: raise HearthError("Slot must be 1 through 5")
                        if store.slots(story)[slot - 1] == "Empty" or input("Replace save? y/N: ").lower() == "y":
                            store.save(engine, slot, timestamp())
                            print("Saved.")
                    elif answer.startswith("l "):
                        engine, note = store.load(story, int(answer[2:]))
                        print(note)
                    elif answer.startswith("d "):
                        if input("Delete save? y/N: ").lower() == "y": store.delete(story, int(answer[2:]))
                    elif engine.phase == "text" and not answer: engine.advance()
                    elif engine.phase == "choice": engine.choose(int(answer) - 1)
                    elif engine.phase == "input": engine.submit_input(answer)
                    elif engine.phase == "ended" and not answer: break
                except (HearthError, OSError, ValueError) as error:
                    print(error_text(error))
        except (HearthError, OSError, ValueError) as error:
            print(error_text(error))


def main():
    root = app_directory()
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        path = sys.argv[2] if len(sys.argv) > 2 else root + "/welcome_to_hearth.hearth"
        with text_open(path) as source: story = Story(source)
        print("Valid: %s | %s scenes | %s instructions" % (story.meta["title"], len(story.scenes), len(story.code)))
        for warning in story.warnings: print(warning)
        return
    try:
        import solaros
        fs = solaros.storage
    except ImportError:
        import os
        fs, solaros = os, None
    store = Store(root, fs)
    if len(sys.argv) > 1:
        if len(sys.argv) != 3 or sys.argv[1] != "--import":
            raise HearthError("Usage: hearth.py [--check [story.hearth] | --import story.hearth]")
        print("Imported: " + store.import_story(sys.argv[2]))
        return
    if solaros: solar_main(solaros, store)
    else: console(store)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        pass
