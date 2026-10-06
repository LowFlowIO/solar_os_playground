"""Hearth's data-only compiler and deterministic interpreter. No story I/O."""
import json
import hashlib
import binascii
import gc

MAX_SOURCE = 131072
MAX_STEPS = 4096
MAX_TRANSCRIPT = 128
MAX_NUMBER = 1000000


class HearthError(Exception):
    pass


def fail(line, message):
    raise HearthError("Line %s: %s" % (line, message))


def clone(value):
    if isinstance(value, dict):
        return {key: clone(child) for key, child in value.items()}
    if isinstance(value, list):
        return [clone(child) for child in value]
    return value


def canonical(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + canonical(value[k])
                              for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    return json.dumps(value)


def checksum(text):
    return binascii.hexlify(hashlib.sha256(text.encode("utf-8")).digest()).decode()


def checksum_value(value):
    """Hash canonical JSON incrementally without allocating the full document."""
    digest = hashlib.sha256()

    def add(text):
        digest.update(text.encode("utf-8"))

    def walk(item):
        if isinstance(item, dict):
            add("{")
            first = True
            for key in sorted(item):
                if not first: add(",")
                first = False
                add(json.dumps(key)); add(":"); walk(item[key])
            add("}")
        elif isinstance(item, list):
            add("[")
            for index, child in enumerate(item):
                if index: add(",")
                walk(child)
            add("]")
        else:
            add(json.dumps(item))

    walk(value)
    return binascii.hexlify(digest.digest()).decode()


def identifier(name):
    return bool(name) and name[0] in "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" and all(
        c in "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in name)


def path_parts(path, line):
    parts = path.split(".")
    if len(parts) < 2 or parts[0].lower() not in ("globals", "local", "characters", "inventory") or not all(identifier(p) for p in parts):
        fail(line, "Invalid state path: " + path)
    return parts


def canonical_key(value, key):
    """Find a mapping key without depending on how it was capitalized."""
    folded = key.lower()
    for existing in value:
        if existing.lower() == folded:
            return existing
    return None


def expand_prompt(text, get_value):
    """Replace {state.path} references using only the SolarOS string API."""
    output, position = [], 0
    while position < len(text):
        start = text.find("{", position)
        if start < 0:
            output.append(text[position:])
            break
        output.append(text[position:start])
        end = text.find("}", start + 1)
        if end < 0:
            output.append(text[start:])
            break
        output.append(display_value(get_value(text[start + 1:end].strip())))
        position = end + 1
    return "".join(output)


def display_value(value):
    """Format scalar state consistently with JavaScript string conversion."""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float and value.is_integer():
        return str(int(value))
    return str(value)


def valid_number_input(text):
    """Check a decimal or exponent-form number without importing re."""
    length, index, digits = len(text), 0, 0
    if index < length and text[index] in "+-": index += 1
    while index < length and text[index].isdigit():
        digits += 1
        index += 1
    if index < length and text[index] == ".":
        index += 1
        while index < length and text[index].isdigit():
            digits += 1
            index += 1
    if digits == 0: return False
    if index < length and text[index] in "eE":
        index += 1
        if index < length and text[index] in "+-": index += 1
        exponent_digits = 0
        while index < length and text[index].isdigit():
            exponent_digits += 1
            index += 1
        if exponent_digits == 0: return False
    return index == length


def scalar(value, line):
    if type(value) not in (str, int, float, bool):
        fail(line, "Expected a string, number, or boolean")
    if type(value) in (int, float) and not (-MAX_NUMBER <= value <= MAX_NUMBER):
        fail(line, "Number must be finite and within +/-1000000")
    if isinstance(value, str) and len(value) > 8192:
        fail(line, "String exceeds 8192 characters")
    return value


def operand(text, line):
    text = text.strip()
    if not text:
        fail(line, "Missing value")
    if text[0] == '"' or text in ("true", "false") or text[0] in "+-0123456789":
        try:
            value = json.loads(text[1:] if text.startswith("+") else text)
        except ValueError:
            fail(line, "Invalid literal: " + text)
        return ("literal", scalar(value, line))
    path_parts(text, line)
    return ("path", text)


def condition(text, line):
    # Operators are recognized only outside quoted strings.
    quoted, escaped = False, False
    for i, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            for op in ("==", "!=", ">=", "<=", ">", "<"):
                if text[i:i + len(op)] == op:
                    return (op, operand(text[:i], line), operand(text[i + len(op):], line))
    fail(line, "Condition requires a comparison")


def source_nodes(source, digest=None):
    """Yield one top-level block at a time, retaining no other parsed blocks."""
    if isinstance(source, str):
        if len(source) > MAX_SOURCE:
            raise HearthError("Story exceeds 128 KiB character limit")
        lines = iter(source.splitlines(keepends=True))
    else:
        lines = iter(source)
    root, stack, number, length = [], None, 0, 0
    stack = [(-1, root)]
    for raw_line in lines:
        number += 1
        if digest is not None:
            digest.update(raw_line.encode("utf-8"))
        length += len(raw_line)
        if length > MAX_SOURCE:
            raise HearthError("Story exceeds 128 KiB character limit")
        raw = raw_line.rstrip("\r\n")
        if "\t" in raw:
            fail(number, "Use spaces, not tabs")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 4:
            fail(number, "Indentation must use four spaces")
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        # Scan comments while preserving quoted colors and bracketed narrative.
        quoted, escaped, narrative, end = False, False, False, None
        for j, ch in enumerate(text):
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif ch == '"' and not narrative:
                quoted = not quoted
            elif ch == "[" and not quoted:
                narrative = True
            elif ch == "]" and narrative:
                narrative = False
            elif ch == "#" and not quoted and not narrative:
                end = j
                break
        if end is not None:
            text = text[:end].rstrip()
        if narrative:
            chunks = [text]
            closed = False
            while True:
                try:
                    continuation = next(lines)
                except StopIteration:
                    break
                number += 1
                if digest is not None:
                    digest.update(continuation.encode("utf-8"))
                length += len(continuation)
                if length > MAX_SOURCE:
                    raise HearthError("Story exceeds 128 KiB character limit")
                piece = continuation.rstrip("\r\n").strip()
                chunks.append(piece)
                # Multiline narrative closes with an unescaped trailing bracket.
                if piece.endswith("]") and not piece.endswith("\\]"):
                    closed = True
                    break
            if not closed:
                fail(number, "Unclosed narrative bracket")
            text = "\n".join(chunks)
        if indent > 64:
            fail(number, "Blocks nested too deeply")
        if indent == 0 and root:
            yield root[0]
            root = []
            stack = [(-1, root)]
        while stack[-1][0] >= indent:
            stack.pop()
        if indent != stack[-1][0] + (1 if stack[-1][0] == -1 else 4):
            fail(number, "Unexpected indentation")
        node = {"text": text, "line": number, "children": []}
        stack[-1][1].append(node)
        stack.append((indent, node["children"]))
    if root:
        yield root[0]


def definitions(nodes):
    result = {}
    for n in nodes:
        text, line = n["text"], n["line"]
        if ":" in text:
            key, value = text.split(":", 1)
            if n["children"] and not value.strip():
                value = definitions(n["children"])
                if not value:
                    fail(line, "Empty definition")
            else:
                if n["children"]:
                    fail(line, "A scalar cannot have a child block")
                parsed = ("literal", value.strip()) if key.lower() == "entry" and identifier(value.strip()) else operand(value, line)
                if parsed[0] != "literal":
                    fail(line, "Initial values must be literals")
                value = parsed[1]
        else:
            key, value = text, definitions(n["children"])
            if not value:
                fail(line, "Empty definition")
        if not identifier(key) or canonical_key(result, key) is not None:
            fail(line, "Invalid or duplicate definition: " + key)
        result[key.lower()] = value
    return result


def narrative(text, line, characters):
    pos = text.find("[")
    if pos < 0 or not text.endswith("]"):
        fail(line, "Expected bracketed narrative")
    prefix, body = text[:pos].strip(), text[pos + 1:-1].strip()
    if len(body) > 8192:
        fail(line, "Narrative block exceeds 8192 characters")
    style, speaker = {}, None
    for token in prefix.split():
        if token in ("text-left", "text-center", "text-right"):
            style["align"] = token[5:]
        elif token.startswith("fadein(") and token.endswith(")"):
            try:
                seconds = float(token[7:-1])
            except ValueError:
                fail(line, "Invalid fade duration")
            if not 0 <= seconds <= 10:
                fail(line, "Fade duration must be 0 to 10 seconds")
            style["fadein"] = seconds
        elif token.startswith('color("#') or token.startswith('background("#'):
            name, arg = token.split("(", 1)
            if not arg.endswith('")'):
                fail(line, "Invalid color")
            color = arg[1:-2]
            if len(color) != 7 or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
                fail(line, "Expected six-digit hex color")
            # style[name] = color - I don't want to deal with color right now.
        elif token in characters and speaker is None:
            speaker = token
        else:
            fail(line, "Unknown speaker or presentation prefix: " + token)
    # Validate placeholders now. Escaped delimiters are resolved at display time.
    j = 0
    while j < len(body):
        if body[j] == "\\":
            j += 2
            continue
        if body[j] == "{":
            end = body.find("}", j + 1)
            if end < 0:
                fail(line, "Unclosed variable placeholder")
            path_parts(body[j + 1:end], line)
            j = end
        j += 1
    return {"body": body, "speaker": speaker, "style": style}


class Story:
    def __init__(self, source):
        streaming = not isinstance(source, str)
        digest = hashlib.sha256() if streaming else None
        self.fingerprint = None if streaming else checksum(source)
        self.code, self.targets, self.scenes, self.warnings = [], {}, [], []
        sections = {}
        for n in source_nodes(source, digest):
            if n["text"].startswith("SCENE "):
                continue
            elif n["text"] in ("GAME", "GLOBALS", "CHARACTERS", "INVENTORY"):
                if n["text"] in sections:
                    fail(n["line"], "Duplicate section")
                sections[n["text"]] = definitions(n["children"])
            else:
                fail(n["line"], "Unknown top-level section")
        if streaming:
            self.fingerprint = binascii.hexlify(digest.digest()).decode()
            source.seek(0)
        self.meta = sections.get("GAME", {})
        for field in ("ID", "Title", "Author", "Revision", "DatePublished", "Genre", "Description", "ContentWarnings", "Entry"):
            actual = canonical_key(self.meta, field)
            if actual is None or not isinstance(self.meta[actual], str) or (field != "ContentWarnings" and not self.meta[actual]):
                raise HearthError("GAME requires string " + field)
        minutes = canonical_key(self.meta, "EstimatedMinutes")
        if minutes is None or type(self.meta[minutes]) not in (int, float) or self.meta[minutes] <= 0:
            raise HearthError("GAME requires positive EstimatedMinutes")
        self.meta = {key.lower(): value for key, value in self.meta.items()}
        self.initial = {"globals": sections.get("GLOBALS", {}), "characters": sections.get("CHARACTERS", {}), "inventory": sections.get("INVENTORY", {}), "local": {}}
        validate_state(self.initial)
        for name, char in self.initial["characters"].items():
            if not isinstance(char, dict) or not isinstance(char.get("name"), str) or type(char.get("hidden")) is not bool:
                raise HearthError("Character requires Name and Hidden: " + name)
            if "shortname" in char and not isinstance(char["shortname"], str):
                raise HearthError("ShortName must be a string: " + name)
        for name, item in self.initial["inventory"].items():
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or type(item.get("player_has")) is not bool:
                raise HearthError("Item requires Name and player_has: " + name)
        for node in source_nodes(source):
            if not node["text"].startswith("SCENE "):
                continue
            scene = node["text"][6:].strip()
            if not identifier(scene) or scene in self.targets:
                fail(node["line"], "Invalid or duplicate scene")
            self.scenes.append(scene)
            self.targets[scene] = len(self.code)
            setup, blocks = [], []
            for child in node["children"]:
                if child["text"] == "START" or child["text"].startswith("LABEL "):
                    blocks.append(child)
                elif blocks:
                    fail(child["line"], "Setup must precede START and labels")
                else:
                    if not child["text"].startswith("VAR."):
                        fail(child["line"], "Scene setup only supports variable operations")
                    setup.append(child)
            if not blocks or blocks[0]["text"] != "START" or sum(b["text"] == "START" for b in blocks) != 1:
                fail(node["line"], "Scene requires one START before labels")

            # Scene-level labels are separate passages. Nested labels are
            # compiled inline and also register their current instruction as
            # a jump destination.
            labels = [child for child in node["children"] if child["text"].startswith("LABEL ")]
            self.compile_block(setup, scene)
            start = blocks[0]
            if not start["children"]:
                fail(start["line"], "Empty narrative block")
            self.compile_block(start["children"], scene)
            self.emit("fallthrough", None, start["line"], scene)
            for block in labels:
                label = block["text"][6:].strip()
                full = scene + "." + label
                if not identifier(label) or full in self.targets:
                    fail(block["line"], "Invalid or duplicate label")
                self.targets[full] = len(self.code)
                if not block["children"]:
                    fail(block["line"], "Empty narrative block")
                self.compile_block(block["children"], scene)
                self.emit("fallthrough", None, block["line"], scene)
            node = blocks = labels = start = setup = child = block = None
            gc.collect()
        if self.meta["entry"] not in self.scenes:
            raise HearthError("GAME.Entry must name a scene")
        for ins in self.code:
            if ins["op"] == "jump":
                target = ins["arg"]
                local = ins["scene"] + "." + target
                resolved = local if "." not in target and local in self.targets else target
                if resolved not in self.targets:
                    fail(ins["line"], "Unknown destination: " + target)
                ins["arg"] = resolved
                if self.scenes.index(resolved.split(".")[0]) < self.scenes.index(ins["scene"]):
                    self.warnings.append("Line %s: backward scene jump to %s" % (ins["line"], resolved))
        # Walk every block's possible paths; accidental fall-through is invalid.
        seen, pending = set(), list(self.targets.values())
        while pending:
            pc = pending.pop()
            if pc in seen:
                continue
            seen.add(pc)
            ins = self.code[pc]
            op = ins["op"]
            if op in ("jump", "end", "fallthrough"):
                continue
            if op == "choice":
                pending.extend(o["pc"] for o in ins["arg"])
            elif op == "goto":
                pending.append(ins["arg"])
            elif op == "if":
                pending.extend((pc + 1, ins["arg"][1]))
            else:
                pending.append(pc + 1)

    def emit(self, op, arg, line, scene):
        self.code.append({"op": op, "arg": arg, "line": line, "scene": scene})
        return len(self.code) - 1

    def compile_block(self, nodes, scene):
        i = 0
        while i < len(nodes):
            n = nodes[i]
            text, line, children = n["text"], n["line"], n["children"]
            i += 1
            if text.startswith("LABEL "):
                label = text[6:].strip()
                full = scene + "." + label
                if not identifier(label) or full in self.targets:
                    fail(line, "Invalid or duplicate label")
                if not children:
                    fail(line, "Empty narrative block")
                self.targets[full] = len(self.code)
                self.compile_block(children, scene)
            elif text == "CHOICE":
                options = []
                self.emit("choice", options, line, scene)
                exits = []
                for opt in children:
                    if not opt["text"].startswith("OPTION "):
                        fail(opt["line"], "CHOICE requires OPTION blocks")
                    display = narrative(opt["text"][7:], opt["line"], {})
                    item = {"display": display, "show": None, "enable": None, "disabled": None, "line": opt["line"]}
                    body = []
                    for child in opt["children"]:
                        directive = child["text"]
                        field = "show" if directive.startswith("SHOW IF ") else "enable" if directive.startswith("ENABLE IF ") else "disabled" if directive.startswith("DISABLED ") else None
                        if field:
                            if body or child["children"] or item[field] is not None:
                                fail(child["line"], "Choice declarations must appear once before commands")
                            item[field] = narrative(directive[9:], child["line"], {}) if field == "disabled" else condition(directive[8:] if field == "show" else directive[10:], child["line"])
                        else:
                            body.append(child)
                    if not body:
                        fail(opt["line"], "Option needs consequences or a continuation")
                    item["pc"] = len(self.code)
                    options.append(item)
                    self.compile_block(body, scene)
                    exits.append(self.emit("goto", None, line, scene))
                if not options:
                    fail(line, "Empty choice")
                for end in exits:
                    self.code[end]["arg"] = len(self.code)
            elif text.startswith("IF "):
                test = self.emit("if", [condition(text[3:], line), None], line, scene)
                if not children:
                    fail(line, "Empty IF")
                self.compile_block(children, scene)
                skip = self.emit("goto", None, line, scene)
                self.code[test]["arg"][1] = len(self.code)
                if i < len(nodes) and nodes[i]["text"] == "ELSE":
                    self.compile_block(nodes[i]["children"], scene)
                    i += 1
                self.code[skip]["arg"] = len(self.code)
            else:
                if children:
                    fail(line, "This command cannot have a child block")
                if text.startswith("JUMP "):
                    self.emit("jump", text[5:].strip(), line, scene)
                elif text in ("END", "CLEAR"):
                    self.emit(text.lower(), None, line, scene)
                elif text.startswith("VAR."):
                    command, _, args = text.partition(" ")
                    if command not in ("VAR.ADD", "VAR.SET", "VAR.CHANGE", "VAR.DEL", "VAR.COPY", "VAR.READ"):
                        fail(line, "Unsupported variable operation")
                    path, comma, value = args.partition(",")
                    path = path.strip()
                    path_parts(path, line)
                    if command == "VAR.READ":
                        parts = value.split(",", 1) if comma else []
                        if len(parts) != 2: fail(line, "VAR.READ requires path, type, prompt")
                        input_type, prompt = parts[0].strip(), parts[1].strip()
                        if input_type not in ("number", "text"): fail(line, "VAR.READ type must be number or text")
                        if not (prompt.startswith('"') and prompt.endswith('"')): fail(line, "VAR.READ prompt must be a quoted string")
                        try: prompt_value = json.loads(prompt)
                        except ValueError: fail(line, "Invalid VAR.READ prompt string")
                        if not isinstance(prompt_value, str): fail(line, "VAR.READ prompt must be text")
                        self.emit("read", (path, input_type, prompt_value), line, scene)
                        continue
                    if (command == "VAR.DEL" and comma) or (command != "VAR.DEL" and not comma):
                        fail(line, "Invalid variable operation arguments")
                    self.emit("copy" if command == "VAR.COPY" else "var", (path, value.strip()) if command == "VAR.COPY" else (command, path, operand(value, line) if comma else None), line, scene)
                elif "[" in text:
                    self.emit("text", narrative(text, line, self.initial["characters"]), line, scene)
                else:
                    fail(line, "Unknown command: " + text)


class Engine:
    def __init__(self, story, start=True):
        self.story = story
        if not start:
            return
        self.story, self.state = story, clone(story.initial)
        self.scene = story.meta["entry"]
        self.pc = story.targets[self.scene]
        self.phase, self.transcript, self.options, self.pending_input = "running", [], [], None
        self.run()

    def get(self, path, line=0):
        value = self.state
        for part in path_parts(path, line):
            if not isinstance(value, dict):
                fail(line, "Unknown variable: " + path)
            key = canonical_key(value, part)
            if key is None: fail(line, "Unknown variable: " + path)
            value = value[key]
        return scalar(value, line)

    def value(self, arg, line):
        return arg[1] if arg[0] == "literal" else self.get(arg[1], line)

    def test(self, arg, line):
        op, lhs, rhs = arg
        a, b = self.value(lhs, line), self.value(rhs, line)
        numeric = type(a) in (int, float) and type(b) in (int, float)
        if not numeric and type(a) is not type(b):
            fail(line, "Comparison types do not match")
        if op not in ("==", "!=") and not numeric:
            fail(line, "Ordering comparisons require numbers")
        if op == "==": return a == b
        if op == "!=": return a != b
        if op == ">=": return a >= b
        if op == "<=": return a <= b
        if op == ">": return a > b
        return a < b

    def rendered(self, arg, line):
        # Spans preserve literal substitutions: player values cannot inject markup.
        text, spans, chunk, i = arg["body"], [], "", 0
        while i < len(text):
            ch = text[i]
            if ch == "\\" and i + 1 < len(text):
                if chunk: spans.append([chunk, False])
                spans.append([text[i + 1], True])
                chunk = ""
                i += 2
                continue
            if ch == "{":
                end = text.find("}", i + 1)
                if chunk: spans.append([chunk, False])
                value = self.get(text[i + 1:end], line)
                spans.append([display_value(value), True])
                chunk, i = "", end + 1
                continue
            chunk += ch
            i += 1
        if chunk: spans.append([chunk, False])
        speaker = arg["speaker"]
        if speaker:
            char_key = canonical_key(self.state["characters"], speaker)
            if char_key is None: raise HearthError("Unknown character: " + speaker)
            char = self.state["characters"][char_key]
            speaker = "?????" if char["hidden"] else char.get("shortname", char["name"])
        return {"spans": spans, "speaker": speaker, "style": clone(arg["style"])}

    def choice_options(self, instruction):
        result = []
        for index, option in enumerate(instruction["arg"]):
            line = option["line"]
            if option["show"] is not None and not self.test(option["show"], line):
                continue
            enabled = option["enable"] is None or self.test(option["enable"], line)
            result.append({"index": index, "display": self.rendered(option["display"], line), "enabled": enabled,
                           "reason": self.rendered(option["disabled"], line) if not enabled and option["disabled"] else None})
        if not any(o["enabled"] for o in result):
            fail(instruction["line"], "Choice has no enabled, visible options")
        return result

    def mutate(self, arg, line):
        command, path, value = arg
        parts = path_parts(path, line)
        parent = self.state
        for part in parts[:-1]:
            actual = canonical_key(parent, part)
            if actual is None or not isinstance(parent[actual], dict):
                fail(line, "Missing variable namespace: " + path)
            parent = parent[actual]
        key = parts[-1]
        actual = canonical_key(parent, key)
        if command == "VAR.ADD":
            if actual is not None: fail(line, "Variable already exists: " + path)
            if len(parent) >= 256: fail(line, "Namespace exceeds 256 variables")
        elif actual is None:
            fail(line, "Unknown variable: " + path)
        elif isinstance(parent[actual], dict):
            fail(line, "Cannot replace or remove a namespace")
        if actual is not None: key = actual
        # Required presentation properties retain their declared types and existence.
        required = (parts[0].lower() == "characters" and len(parts) == 3 and key.lower() in ("name", "shortname", "hidden")) or (parts[0].lower() == "inventory" and len(parts) == 3 and key.lower() in ("name", "player_has"))
        if command == "VAR.DEL":
            if required: fail(line, "Cannot delete required property")
            del parent[key]
            return
        new = self.value(value, line)
        if command == "VAR.CHANGE":
            if type(new) not in (int, float) or type(parent[key]) not in (int, float):
                fail(line, "VAR.CHANGE requires numbers")
            new += parent[key]
        if key in parent and type(parent[key]) is not type(new) and not (type(parent[key]) in (int, float) and type(new) in (int, float)):
            fail(line, "Assignment types do not match")
        parent[key] = scalar(new, line)

    def jump(self, target):
        scene = target.split(".")[0]
        if scene != self.scene or "." not in target:
            self.state["local"] = {}
        self.scene, self.pc = scene, self.story.targets[target]

    def run(self):
        self.phase = "running"
        for unused in range(MAX_STEPS):
            ins = self.story.code[self.pc]
            op, arg, line = ins["op"], ins["arg"], ins["line"]
            if op == "text":
                self.transcript.append(self.rendered(arg, line))
                self.transcript = self.transcript[-MAX_TRANSCRIPT:]
                self.phase = "text"
                return
            if op == "choice":
                self.options = self.choice_options(ins)
                self.phase = "choice"
                return
            if op == "read":
                path, input_type, prompt = arg
                target = self.get(path, line)
                if type(target) is not (float if input_type == "number" and type(target) is float else int if input_type == "number" else str):
                    fail(line, input_type.capitalize() + " input destination has the wrong type")
                prompt = expand_prompt(prompt, lambda path: self.get(path, line))
                self.pending_input = {"path": path, "type": input_type, "prompt": prompt}
                self.phase = "input"
                return
            if op in ("end", "fallthrough"):
                index = self.story.scenes.index(self.scene) + 1
                if index == len(self.story.scenes):
                    self.phase = "ended"
                    return
                self.jump(self.story.scenes[index])
                continue
            if op == "jump":
                self.jump(arg)
                continue
            if op == "goto":
                self.pc = arg
                continue
            if op == "if" and not self.test(arg[0], line):
                self.pc = arg[1]
                continue
            if op == "var": self.mutate(arg, line)
            elif op == "copy":
                path, source = arg
                value, target = self.get(source, line), self.get(path, line)
                if type(target) is not type(value) and not (type(target) in (int, float) and type(value) in (int, float)):
                    fail(line, "Variable copy types do not match")
                self.set_existing(path, value, line)
            elif op == "clear": self.transcript = []
            self.pc += 1
        fail(self.story.code[self.pc]["line"], "Too many commands without player interaction (possible loop)")

    def advance(self):
        if self.phase != "text": raise HearthError("Not waiting for text advancement")
        self.pc += 1
        self.run()

    def set_existing(self, path, value, line):
        parts = path_parts(path, line)
        parent = self.state
        for part in parts[:-1]:
            actual = canonical_key(parent, part)
            if actual is None or not isinstance(parent[actual], dict): fail(line, "Missing variable namespace: " + path)
            parent = parent[actual]
        key = parts[-1]
        actual = canonical_key(parent, key)
        if actual is None or isinstance(parent[actual], dict): fail(line, "Unknown or non-scalar destination variable: " + path)
        key = actual
        parent[key] = scalar(value, line)

    def submit_input(self, value):
        if self.phase != "input" or not self.pending_input: raise HearthError("Not waiting for input")
        pending = self.pending_input
        clean = "".join(ch for ch in str(value) if ord(ch) >= 32 and not 127 <= ord(ch) <= 159).strip()
        if not clean: raise HearthError("Please enter a value")
        if len(clean) > 8192: raise HearthError("Input must be 8192 characters or fewer")
        if pending["type"] == "number":
            if not valid_number_input(clean):
                raise HearthError("Enter a valid number between -1000000 and 1000000")
            try: parsed = float(clean) if any(c in clean for c in ".eE") else int(clean)
            except ValueError: raise HearthError("Enter a valid number between -1000000 and 1000000")
            if type(parsed) not in (int, float) or abs(parsed) > MAX_NUMBER: raise HearthError("Enter a valid number between -1000000 and 1000000")
        else: parsed = clean
        self.set_existing(pending["path"], parsed, self.story.code[self.pc]["line"])
        self.transcript.append({"spans": [[clean, True]], "speaker": "You", "style": {}})
        self.transcript = self.transcript[-MAX_TRANSCRIPT:]
        self.pending_input = None
        self.pc += 1
        self.run()

    def choose(self, index):
        if self.phase != "choice": raise HearthError("Not waiting for a choice")
        if not any(o["index"] == index and o["enabled"] for o in self.options):
            raise HearthError("Option is hidden, disabled, or unknown")
        option = self.story.code[self.pc]["arg"][index]
        display = next(item["display"] for item in self.options if item["index"] == index)
        self.transcript.append({"spans": clone(display["spans"]), "speaker": "You", "style": clone(display["style"])})
        self.transcript = self.transcript[-MAX_TRANSCRIPT:]
        self.pc = option["pc"]
        self.options = []
        self.run()

    def snapshot(self, timestamp):
        if self.phase not in ("text", "choice", "input", "ended"):
            raise HearthError("Cannot save a partially executed command batch")
        data = {"format": 1, "game": self.story.meta["id"], "revision": self.story.meta["revision"], "fingerprint": self.story.fingerprint,
                "scene": self.scene, "pc": self.pc, "phase": self.phase, "state": clone(self.state), "transcript": clone(self.transcript), "saved_at": timestamp}
        return {"data": data, "checksum": checksum_value(data)}

    @classmethod
    def restore(cls, story, envelope):
        try:
            data = envelope["data"]
            if envelope["checksum"] != checksum_value(data):
                raise HearthError("Save integrity check failed")
            if data["format"] != 1 or data["game"] != story.meta["id"] or data["revision"] != story.meta["revision"] or data["fingerprint"] != story.fingerprint:
                raise HearthError("Save is incompatible with this story revision")
            pc, phase = data["pc"], data["phase"]
            if type(pc) is not int or not 0 <= pc < len(story.code) or phase not in ("text", "choice", "input", "ended"):
                raise HearthError("Invalid saved execution position")
            ins = story.code[pc]
            expected_op = "end" if phase == "ended" else "read" if phase == "input" else phase
            if ins["scene"] != data["scene"] or ins["op"] != expected_op:
                raise HearthError("Saved phase does not match instruction")
            state = data["state"]
            if not isinstance(state, dict) or set(key.lower() for key in state) != set(key.lower() for key in story.initial) or not all(isinstance(v, dict) for v in state.values()):
                raise HearthError("Invalid saved state")
            validate_state(state)
            for ns in ("characters", "inventory"):
                for key, initial in story.initial[ns].items():
                    state_key = canonical_key(state[ns], key)
                    if state_key is None: raise HearthError("Saved state is missing a declared entity")
                    current = state[ns][state_key]
                    if set(field.lower() for field in current) != set(field.lower() for field in initial):
                        raise HearthError("Saved entity properties do not match story definitions")
                    for field in (("name", "hidden") if ns == "characters" else ("name", "player_has")):
                        field_key = canonical_key(current, field)
                        initial_key = canonical_key(initial, field)
                        if field_key is None or initial_key is None or type(current[field_key]) is not type(initial[initial_key]):
                            raise HearthError("Invalid saved required property")
            transcript = data["transcript"]
            if not isinstance(transcript, list) or len(transcript) > MAX_TRANSCRIPT:
                raise HearthError("Invalid saved transcript")
            for entry in transcript:
                if not isinstance(entry, dict) or not isinstance(entry["style"], dict) or (entry["speaker"] is not None and not isinstance(entry["speaker"], str)):
                    raise HearthError("Invalid saved text entry")
                if not isinstance(entry["spans"], list) or any(not isinstance(s, list) or len(s) != 2 or not isinstance(s[0], str) or type(s[1]) is not bool for s in entry["spans"]):
                    raise HearthError("Invalid saved text spans")
            # Avoid depending on CPython's object construction internals.
            engine = cls(story, False)
            engine.story, engine.state = story, clone(state)
            engine.pc, engine.scene, engine.phase = pc, data["scene"], phase
            engine.transcript = clone(transcript)
            if phase == "input":
                prompt = expand_prompt(ins["arg"][2], lambda path: engine.get(path, ins["line"]))
                engine.pending_input = {"path": ins["arg"][0], "type": ins["arg"][1], "prompt": prompt}
            else: engine.pending_input = None
            engine.saved_at = data["saved_at"]
            engine.options = engine.choice_options(ins) if phase == "choice" else []
            return engine
        except (KeyError, TypeError, ValueError, IndexError):
            raise HearthError("Malformed save file")


def validate_state(value, depth=0):
    if depth > 16: raise HearthError("State nesting exceeds limit")
    if isinstance(value, dict):
        if len(value) > 256: raise HearthError("Too many state variables")
        for key, child in value.items():
            if not identifier(key): raise HearthError("Invalid saved variable name")
            validate_state(child, depth + 1)
    else:
        scalar(value, 0)
