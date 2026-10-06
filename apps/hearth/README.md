# Hearth 1.0

Self-contained, choice-driven text adventures for SolarOS. Includes **The Last Light**, a complete sample with two endings.

The optional `hearth` alias launches the player. Stories can be written directly from the language reference or with the [browser-based authoring tool](https://www.heyvictorfrost.com/solaros/hearth/studio/).

## Run on SolarOS

Copy this directory to `/apps/hearth/`, then run:

```text
python /apps/hearth/hearth.py
```

The `alias` file contains the optional shell shortcut. `manifest.json` follows the existing SolarOS app format. No firmware changes or external dependencies are required.

The player uses a foreground display and falls back to the terminal when launched from a port shell without one. It renders stories as high-contrast black text on white and ignores story colors for one-bit display legibility. Bold, italic, and strike-through remain available; firmware italic fonts may appear upright.

Controls:

| Key | Action |
| --- | --- |
| Enter / Space | Advance text, or select the highlighted option |
| Up / Down | Select a choice (disabled options remain readable) |
| Page Up / Page Down | Scroll the transcript |
| S / L | Save / load; five slots per adventure |
| Escape | Pause menu; continue, save, load, or return to library |

New dialogue follows the bottom of the accumulated transcript, keeping earlier lines visible wherever space permits. Choices share that transcript view and scroll only enough to keep the highlighted option visible. Authored `CLEAR` commands still empty the transcript. Long text is paginated from its first line before advancing. Saves at a choice do not select it; saves at a `VAR.READ` prompt restore the unanswered prompt. Returning to the library discards unsaved progress; saves are manual.

The adventure menu also provides metadata, content warnings, save deletion, and **Delete this adventure**. Deleting an adventure removes it from the library along with its local story file and all five save slots, after confirmation. In the desktop console, enter `d N` at the library prompt and confirm with `y` to delete adventure N.

## Featured stories

Choose **Featured stories** from the main menu to fetch the current catalog from `https://www.heyvictorfrost.com/hearth/player/stories/manifest.json`. Select a story to review its description and download it into the local library. Hearth checks the response, validates the story, and confirms its `GAME.ID` matches the catalog before installing it. Reopening the submenu fetches the manifest again; **Refresh featured list** polls it again without leaving the submenu.

This feature needs Wi-Fi and a SolarOS build with `solaros.http` available. Local stories and saves continue to work when the catalog cannot be reached.

## Add a story

```text
python /apps/hearth/hearth.py --import /path/to/adventure.hearth
```

Import validates the story, copies it under a generated filename, and registers it in `library.json`. The original file is untouched. Duplicate game IDs are rejected; use a distinct ID for a separate adventure. Importing replacements for an installed game is not yet supported. The built-in sample loads without an index file.

Stories cannot execute code or access paths, network services, other adventures, or other apps. Import and save operations are provided by the host application; no story command invokes them.

## Saves and compatibility

Saves live beneath this app's `saves/` directory in a folder generated from the game ID. Each numbered slot records its timestamp, revision, source fingerprint, scene, instruction, interaction phase, state, and visible transcript. SHA-256 checks detect corruption, not cheating.

Writes use a temporary file and retain a backup generation. Loading tries the primary, then complete temporary/backup generations when necessary, and reports recovery. An incompatible revision or source fingerprint is rejected. Even a comment edit changes the current fingerprint. Do not edit stories if you need their existing saves to remain loadable.

## Implementation and limits

- `hearth_core.py`: parser, validation, compiled instructions, interpreter, snapshots.
- `hearth_storage.py`: host-owned import, library, slots, and recovery.
- `hearth_view.py`: styled text wrapping and SolarOS rendering.
- `hearth.py`: app lifecycle, controls, menus, console preview, and validation command.
- `hearth_featured.py`: hosted catalog polling, download validation, and installation.
- `AUTHORING.md`: language reference.

Scene-local labels may be declared anywhere beneath a scene and can be nested within other blocks. Sources are limited to 128 Ki characters, text blocks and scalar strings to 8192 characters, each variable namespace to 256 entries, and numbers to +/-1,000,000. Up to 64 adventures may be registered. The transcript retains the latest 128 text blocks after `CLEAR`; it is not an unlimited history archive. At most 4096 commands run between player interactions.

Free-form command parsing, automatic combat/item modifiers, arbitrary coordinates, auto-save, and save migration are not implemented. Authored text/number input uses `VAR.READ`; keyboard input is the initial interaction method.
