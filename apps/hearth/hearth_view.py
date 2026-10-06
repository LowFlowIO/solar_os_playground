"""Text layout shared by Hearth's SolarOS player and host tests."""

# Graphical palette: black on white. Selection is inverse video (white on
# black). Story-provided foreground/background colors are intentionally ignored
# for legibility on the one-bit reflective display.
BACKGROUND = "#FFFFFF"
TEXT = "#000000"
TITLE = "#000000"
RULE = "#000000"
FOOTER = "#000000"
DISABLED = "#000000"
SELECTED_BACKGROUND = "#000000"
SELECTED_TEXT = "#FFFFFF"
SELECTED_DISABLED = "#A0A0A0"


def plain(entry):
    return "".join(span[0] for span in entry["spans"])


def styled_chars(entry):
    flags = 0  # bold=1, italic=2, strike=4
    result = []
    if entry.get("speaker"):
        result.extend((c, 1) for c in entry["speaker"] + ": ")
    for text, literal in entry["spans"]:
        i = 0
        while i < len(text):
            if not literal:
                if text[i:i + 2] == "**":
                    flags ^= 1
                    i += 2
                    continue
                if text[i:i + 2] == "~~":
                    flags ^= 4
                    i += 2
                    continue
                if text[i] == "*":
                    flags ^= 2
                    i += 1
                    continue
            char = text[i]
            # Do not send terminal control sequences or carriage returns to a view.
            if char != "\n" and (ord(char) < 32 or ord(char) == 127):
                char = " "
            result.append((char, flags))
            i += 1
    return result


def wrap_entry(entry, width):
    width = max(1, width)
    rows, current = [], []
    for char in styled_chars(entry):
        if char[0] == "\n":
            rows.append(current)
            current = []
            continue
        current.append(char)
        if len(current) > width:
            split = -1
            for index in range(len(current) - 1, -1, -1):
                if current[index][0] == " ":
                    split = index
                    break
            if split <= 0:
                rows.append(current[:width])
                current = current[width:]
            else:
                rows.append(current[:split])
                current = current[split + 1:]
    if current or not rows:
        rows.append(current)
    return rows


def literal_entry(text):
    return {"spans": [[str(text), True]], "speaker": None, "style": {}}


def layout(engine, width, cache=None):
    rows, last, choices = [], 0, []
    entries = engine.transcript
    old_entries = cache.get("entries", []) if cache is not None and cache.get("width") == width else []
    old_chunks = cache.get("chunks", []) if old_entries else []
    offset = 0
    if entries and old_entries:
        for index, old in enumerate(old_entries):
            if old is entries[0]:
                offset = index
                break
        else:
            old_entries, old_chunks = [], []
    chunks = []
    reusable = len(old_entries) - offset
    for index, entry in enumerate(entries):
        if index < reusable and old_entries[offset + index] is entry:
            chunk = old_chunks[offset + index]
        else:
            chunk = [{"chars": chars, "style": entry["style"], "option": None, "enabled": True}
                     for chars in wrap_entry(entry, width)]
        chunks.append(chunk)
        last = len(rows)
        rows.extend(chunk)
        rows.append({"chars": [], "style": {}, "option": None, "enabled": True})
    if cache is not None:
        cache["width"], cache["entries"], cache["chunks"] = width, list(entries), chunks
    if engine.phase == "choice":
        for pos, option in enumerate(engine.options):
            choices.append(len(rows))
            entry = dict(option["display"])
            entry["spans"] = [["  ", True]] + entry["spans"]
            rows.extend({"chars": chars, "style": {}, "option": pos, "enabled": option["enabled"]} for chars in wrap_entry(entry, width))
            if option["reason"]:
                rows.extend({"chars": chars, "style": {}, "option": pos, "enabled": False} for chars in wrap_entry(option["reason"], width))
            rows.append({"chars": [], "style": {}, "option": None, "enabled": True})
    return rows, last, choices


def reading_top(rows, choices, phase, height, last=0):
    """Choose the initial viewport while keeping recent story text visible."""
    height = max(1, height)
    bottom = max(0, len(rows) - height)
    if phase != "choice" or not choices:
        # Start oversized passages at their first line so Enter can page through
        # them. Short passages follow the bottom like the web reader and retain
        # as much preceding dialogue as the display can hold.
        if phase == "text" and len(rows) - last > height:
            return max(0, last)
        return bottom

    # When every option fits, anchor the viewport at the bottom. This uses all
    # remaining space for the most recent story text instead of discarding it.
    choice_rows = len(rows) - choices[0]
    if choice_rows <= height:
        return bottom

    # A very long choice cannot share a page with all of its options. Keep the
    # final line before the choice as context and start at the first option.
    return max(0, choices[0] - 1)


def follow_choice(rows, choices, selected, top, height):
    """Scroll only as far as needed to keep the selected option fully visible."""
    if not choices:
        return top
    height = max(1, height)
    selected = max(0, min(len(choices) - 1, selected))
    first = choices[selected]
    last = first
    while last + 1 < len(rows) and rows[last + 1]["option"] == selected:
        last += 1
    if first < top:
        top = first
    elif last >= top + height:
        top = last - height + 1
    return max(0, min(max(0, len(rows) - height), top))


class SolarView:
    def __init__(self, solaros):
        self.solaros, self.gfx, self.tui = solaros, solaros.gfx, solaros.tui
        self.graphical = False
        try:
            self.gfx.begin()
            self.graphical = True
        except RuntimeError:
            pass  # A port shell has no foreground display; use its terminal.
        self.animations = False
        self.measure()

    def measure(self):
        if self.graphical:
            width, height = self.gfx.size()
            self.cols, self.rows = max(1, (width - 16) // 8), max(1, (height - 72) // 16)
        else:
            rows, cols = self.tui.size()
            self.cols, self.rows = max(1, cols - 2), max(1, rows - 3)

    def now(self):
        return self.solaros.time.uptime_ms()

    def key(self, timeout=250):
        return (self.gfx if self.graphical else self.tui).getch(timeout)

    def closing(self):
        return self.solaros.should_exit()

    def iskey(self, key, name):
        return key == getattr(self.gfx if self.graphical else self.tui, "KEY_" + name, -999)

    def color(self, value):
        return self.gfx.rgb(int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))

    def frame(self, title, rows, top=0, selected=-1, footer="", fade_start=None, fade=1.0):
        self.measure()
        if self.graphical:
            g = self.gfx
            g.clear(self.color(BACKGROUND))
            g.color(self.color(TITLE))
            g.font(g.FONT_BOLD_14)
            g.text(8, 19, title[:self.cols])
            g.color(self.color(RULE))
            g.line(8, 28, g.width() - 8, 28)
        else:
            self.tui.clear()
            self.tui.addstr(0, 0, title[:self.cols], self.tui.BOLD)
            
        for position, row in enumerate(rows[top:top + self.rows]):
            chars, style = row["chars"], row["style"]
            align = style.get("align", "left")
            offset = max(0, (self.cols - len(chars)) // 2 if align == "center" else self.cols - len(chars) if align == "right" else 0)
            active = row["option"] is not None and row["option"] == selected
            
            if self.graphical:
                g = self.gfx
                y = 36 + position * 16
                if active:
                    background = SELECTED_BACKGROUND
                    foreground = SELECTED_TEXT if row["enabled"] else SELECTED_DISABLED
                else:
                    background = BACKGROUND
                    foreground = TEXT if row["enabled"] else DISABLED
                ink = self.color(foreground)
                    
                g.color(self.color(background))
                g.fill_rect(8, y, self.cols * 8, 16)
                g.color(ink)

                # Batch adjacent characters into styled runs
                visible_chars = chars[:self.cols]
                if visible_chars:
                    runs = []
                    current_text = visible_chars[0][0]
                    current_flags = visible_chars[0][1]

                    for char, flags in visible_chars[1:]:
                        if flags == current_flags:
                            current_text += char
                        else:
                            runs.append((current_text, current_flags))
                            current_text, current_flags = char, flags
                    runs.append((current_text, current_flags))

                    # Render batched text runs
                    col_index = offset
                    for text_segment, flags in runs:
                        g.font(g.FONT_BOLD_ITALIC_14 if flags & 3 == 3 else g.FONT_BOLD_14 if flags & 1 else g.FONT_ITALIC_14 if flags & 2 else g.FONT_MONO_14)
                        x = 8 + col_index * 8
                        g.text(x, y + 14, text_segment)
                        
                        # Batched strikethrough line across the entire run
                        if flags & 4:
                            segment_width = len(text_segment) * 8
                            g.line(x, y + 7, x + segment_width - 1, y + 7)
                            
                        col_index += len(text_segment)
            else:
                for column, (char, flags) in enumerate(chars[:self.cols]):
                    attr = self.tui.INVERSE if active else self.tui.BOLD if flags & 1 else self.tui.NORMAL
                    self.tui.addstr(position + 1, column + offset, char, attr)
                    
        if self.graphical:
            g.font(g.FONT_MONO_12)
            g.color(self.color(FOOTER))
            g.text(8, g.height() - 21, footer[:self.cols])
            g.text(8, g.height() - 6, footer[self.cols:self.cols * 2])
            g.present()
        else:
            self.tui.addstr(self.rows + 1, 0, footer[:self.cols])
            self.tui.addstr(self.rows + 2, 0, footer[self.cols:self.cols * 2])
            self.tui.refresh()

    def menu(self, title, items):
        selected, top, dirty, follow = 0, 0, True, True
        self.measure()
        rows, starts = [], []
        for index, item in enumerate(items):
            starts.append(len(rows))
            for chars in wrap_entry(literal_entry(item), self.cols):
                rows.append({"chars": chars, "style": {}, "option": index, "enabled": True})
        while not self.closing():
            if dirty:
                self.measure()
                if follow and (starts[selected] < top or starts[selected] >= top + self.rows):
                    top = starts[selected]
                self.frame(title, rows, top, selected, "Up/Down select  Enter open  Esc back")
                dirty = False
            key = self.key()
            if key is None: continue
            if self.iskey(key, "ESCAPE") or key == ord("q"): return None
            if self.iskey(key, "UP"):
                new_selected = max(0, selected - 1)
                if new_selected != selected:
                    selected, dirty, follow = new_selected, True, True
            elif self.iskey(key, "DOWN"):
                new_selected = min(len(items) - 1, selected + 1)
                if new_selected != selected:
                    selected, dirty, follow = new_selected, True, True
            elif self.iskey(key, "PAGE_DOWN"):
                new_top = min(max(0, len(rows) - self.rows), top + self.rows)
                if new_top != top: top, dirty = new_top, True
                follow = False
            elif self.iskey(key, "PAGE_UP"):
                new_top = max(0, top - self.rows)
                if new_top != top: top, dirty = new_top, True
                follow = False
            elif key in (10, 13): return selected
        return None

    def message(self, title, text):
        rows = [{"chars": chars, "style": {}, "option": None, "enabled": True} for chars in wrap_entry(literal_entry(text), self.cols)]
        top, dirty = 0, True
        while not self.closing():
            if dirty:
                self.frame(title, rows, top, footer="Enter/PgDn more  Esc back")
                dirty = False
            key = self.key()
            if key is None: continue
            dirty = True
            if self.iskey(key, "ESCAPE") or key == ord("q"): return
            if self.iskey(key, "PAGE_UP"): top = max(0, top - self.rows)
            if key in (10, 13) or self.iskey(key, "PAGE_DOWN"):
                if top + self.rows >= len(rows): return
                top += self.rows

    def input_text(self, title, prompt, input_type):
        value, dirty = "", True
        while not self.closing():
            if dirty:
                self.measure()
                rows = []
                for line in (prompt, "", value[-max(1, self.cols - 1):] + "_", "", "Enter submit   Esc cancel"):
                    rows.extend({"chars": chars, "style": {}, "option": None, "enabled": True} for chars in wrap_entry(literal_entry(line), self.cols))
                self.frame(title, rows, 0, footer="Type response and press Enter")
                dirty = False
            key = self.key()
            if key is None: continue
            if self.iskey(key, "ESCAPE"): return None
            if key in (10, 13): return value
            if key in (8, 127) or self.iskey(key, "BACKSPACE"):
                value = value[:-1]
                dirty = True
            elif key >= 32 and not 127 <= key <= 159 and len(value) < 8192:
                char = chr(key)
                if input_type != "number" or char in "0123456789+-.eE":
                    value += char
                    dirty = True

    def close(self):
        import gc
        gc.collect()
        if self.graphical:
            self.gfx.end()
        else:
            self.tui.clear()
            self.tui.refresh()
