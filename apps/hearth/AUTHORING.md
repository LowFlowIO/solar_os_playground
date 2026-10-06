# Writing a Hearth adventure

## Files and definitions

Files are UTF-8 with the `.hearth` extension. Use four spaces for each indentation level; tabs are rejected. Commands and label names are case-sensitive. Variable path components resolve without regard to case. `#` begins a comment outside quoted strings and narrative brackets.

Top-level blocks are `GAME`, `CHARACTERS`, `INVENTORY`, `GLOBALS`, and `SCENE name`. The first four cannot be duplicated. Character/inventory/global blocks may be omitted when unused.

`GAME` requires string values for `ID`, `Title`, `Author`, `Revision`, `DatePublished`, `Genre`, `Description`, `ContentWarnings`, and `Entry`, plus positive numeric `EstimatedMinutes`. Content warnings may be an empty string. `Entry` can be a quoted or bare scene name. Give each adventure its own stable ID.

Definitions use `property: value`. Strings use JSON-style double quotes and escapes; booleans are lowercase `true` and `false`; numbers may be integers or decimals. Null values are not supported. Use `""` for an initially empty text value and `0` for an initially empty numeric value, such as a variable that will receive player input. Nested property groups create namespaces, not executable objects. Character definitions require `Name` and boolean `Hidden`; `ShortName` is optional. Item definitions require `Name` and boolean `player_has`. Add descriptive and gameplay properties as needed.

Initial values are literals. All definitions exist before entry into the first scene. Item stats and relationship modifiers do nothing automatically; apply them explicitly in the script.

## Scenes and labels

```text
SCENE arrival
    VAR.ADD local.weather, "cold"

    START
        [The night is {local.weather}.]
        JUMP greeting

    LABEL greeting
        [Someone waves you inside.]
        END
```

Setup variable operations precede one `START` block. Normal scene entry executes setup. A jump to `arrival.greeting` skips setup and `START`. An internal jump preserves the current scene's local state; leaving the scene discards it. Direct entry into another scene's label starts with empty local state, so that label must not assume setup variables exist.

Labels may be declared anywhere inside a scene, including inside a conditional branch, choice option, or another label. Scene-level labels are separate passages and only run when jumped to. Nested labels run inline when normal flow reaches them, and also provide jump destinations. Their names are scene-local, so a jump uses `arrival.greeting` regardless of the label's indentation. Bare label names resolve in the current scene, then among top-level scenes. Local labels take precedence. Qualified destinations are exact. Duplicate names in a scene and missing destinations are errors. Backward scene jumps produce warnings.

`END` ends the enclosing scene, entering the next sibling scene's setup or finishing the adventure if none exists. It never falls into another label. Use labels inside the final scene for alternative endings. 

Narrative flow continues through later blocks and labels within the same scene. It does not automatically continue into the next scene; if a path reaches the end of its scene without a JUMP or END, the story ends.

## Text and presentation

```text
[An unvoiced narrative line.]
mara [A spoken line.]
text-center [**A title**]
mara [A quiet arrival.]
[
    A multiline block.

    A second paragraph in the same block.
]
```

Every block waits for player advancement. A character's hidden flag displays `?????`; revealing it affects subsequent dialogue, preserving old headers. Bold uses `**text**`, italic uses `*text*`, and strike-through uses `~~text~~`. Formatting may be combined. Prefix alignment is `text-left`, `text-center`, or `text-right`.

`{globals.player_name}` substitutes a scalar literally; substitution cannot inject formatting. Use a backslash before a literal bracket, brace, asterisk, tilde, or backslash. For example, `[Read \[the note\].]`. Multiline closing brackets must finish their line. Presentation uses the player's text display.

## State operations and conditions

```text
VAR.ADD globals.visits, 0
VAR.CHANGE globals.visits, +1
VAR.SET characters.mara.Hidden, false
VAR.CHANGE characters.mara.Relationship, inventory.key.trust_bonus
VAR.DEL local.temporary_note
VAR.COPY globals.previous_destination, globals.destination
VAR.READ globals.player_name, text, "What is your name?"
VAR.READ globals.blueberry_count, number, "How many blueberries will you give up?"

IF characters.mara.Relationship >= 2
    JUMP trusted
ELSE
    JUMP uncertain
```

`ADD` creates a new scalar; `SET` changes an existing scalar; `CHANGE` adds a numeric amount to an existing number; `DEL` removes a scalar. `COPY destination, source` copies one declared scalar into another declared scalar of the same type. `READ destination, number|text, "prompt"` pauses for player input and stores it in an existing variable of the selected type. A text input destination starts as a string (use `""` if it has no initial contents); a number destination starts as a number (often `0`). Number input accepts finite decimal or exponent notation within +/-1,000,000; invalid answers leave the prompt open. Text input trims surrounding whitespace, removes control characters, rejects blank values, and is limited to 8192 characters. Player responses remain literal data and are never parsed as Hearth commands or executable code. Parent namespaces must already exist. Undeclared variables, duplicate creation, changes to whole namespaces, or mismatched scalar types are errors. Required character and item properties cannot be deleted. Arithmetic results remain within the numeric limit.

Conditions compare two literals or variable paths with `==`, `!=`, `>`, `<`, `>=`, or `<=`. Equality works on matching scalar types. Ordering requires numbers. There are no general-purpose expressions, function calls, imports, or filesystem operations. Use nested conditions for more complex decisions.

## Choices

```text
CHOICE
    OPTION [Open the locked door.]
        ENABLE IF inventory.key.player_has == true
        DISABLED [Requires the key.]
        VAR.SET globals.door_open, true
        JUMP doorway

    OPTION [Mention the hidden passage.]
        SHOW IF globals.knows_passage == true
        JUMP passage

    OPTION [Leave.]
        JUMP departure
```

Choice declarations precede consequences and appear at most once per option. `SHOW IF` hides an option when false; `ENABLE IF` keeps it visible but unavailable; `DISABLED` supplies the reason. A choice with no usable options reports an authoring error. Always consider an unconditional fallback.

An option may jump or execute consequences and continue after the whole `CHOICE` block. Unselected options never run. Consequences and transfers execute until the next text, choice, or ending before a save can capture them. Saves are player operations: scripts do not declare save paths, slots, or commands.

## Validation

If you are editing on SolarOS, validate edits with `python hearth.py --check your-story.hearth`; validation does not execute the story or prove every state-dependent path is error-free.

## Review before sharing

Validate the file, play every route, check conditions at their boundary values, and test save/resume at choices. The static checker catches structure and destinations; dynamic state errors still require route testing. Keep game IDs stable, increment revisions for releases, and remember that this version rejects saves after any source edit.
