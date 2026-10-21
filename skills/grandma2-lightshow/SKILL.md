---
name: grandma2-lightshow
description: Create a song-synchronised light show in grandMA2 (onPC or console) with the grandma2 MCP tools. Use when the user gives a song/audio file and wants a light show, asks to program cues/effects to music, or wants to patch fixtures in grandMA2.
---

# Song → grandMA2 light show

Tools come from the `grandma2` MCP server (`ma_*`, `song_*`, `show_*`). If they are
missing, the MCP server is not installed or grandMA2 is not reachable — see the repo README.

## 1. Check the console

1. `ma_status`, then `ma_command("List Fixture")`.
   - Connection error → onPC not running, or Telnet is off
     (Setup → Console → Global Settings → Telnet: **Login Enabled**).
2. No fixtures? Ask the user what rig they have (or offer a demo rig), then
   `ma_find_fixture_type("<manufacturer> <model>")` and `ma_patch(...)`.
   Demo rig that works everywhere: 8× `generic@led_-_rgbw@8_bit` (IDs 101–108, universe 1)
   + 10× generic dimmer (type `2`, IDs 201–210, universe 2).
3. `ma_command("List Attribute")` — use exactly these attribute names.
   Generic LEDs: R=`ColorRGB1`, G=`ColorRGB2`, B=`ColorRGB3`, White=`ColorRGB5`, dimmer via `At`.
   Moving heads: `Pan`, `Tilt`, gobo/colour wheels — check the list.
4. `ma_command("List Effect")`. Empty → `ma_command('Import "predefined" At Effect 1 /nc')`
   (1 Dimmer Sin, 2 Dimmer Chase, 3 Dimmer PWM, 4 Dimmer Random, 5 Dimmer Even/Odd,
   7 RGB Rainbow, 9 RGB Chase, 10 RGB Blue White, 11 RGB Even/Odd, 12 RGB Random,
   17 Dim/P/T Ballyhoo, 19 Tilt Sin, 20 Pan Sin, 23 P/T Circle, 24 P/T Wave, 25 P/T Cross).
5. Pick a free sequence number (`List Sequence`) and a free executor (`List Executor 1.1` …).

## 2. Analyse the song

`song_analyze(path)` returns BPM, beat grid, sections (start/end, energy, level, change),
accents (drops/lifts) and per-bar energy. Use `include_beats=True` only when you need
per-beat cues.

- `grid_fit` ≥ 0.8: steady tempo — beat-locked cues and `EffectBPM <bpm>` will stay in sync.
- `grid_fit` < 0.6: live/rubato — avoid per-beat chases, cue on sections/accents only.
- Section `level` low/mid/high and `change` (drop/lift, breakdown) drive the look.
- Read the bars line to spot build-ups (energy rising over 4–8 bars) and the last bar
  before a drop (good spot for a blackout or strobe).

## 3. Design the show (write the plan down briefly before building)

Rules of thumb:
- **One look per section**, changes on downbeats (bar starts). Musical phrases are 4/8/16 bars.
- **Intensity follows energy**: low → 20–40 %, mid → 50–80 %, high → 100 %.
- **Colour per section type**: keep 2–3 palettes and repeat them when a section returns
  (same verse colour each verse, same chorus colour each chorus) — repetition reads as design.
  Calm parts: blue/purple/amber. Builds: saturate, add movement. Drops: white flash, then
  strong contrast (red/white, cyan/magenta).
- **Movement/effects** = song BPM (or BPM/2 for half-time feel):
  `Fixture 101 Thru 108; At Effect 9; PresetType "Color"; EffectBPM 128`.
  EffectBPM applies to the active PresetType ("Dimmer", "Position", "Color", "Beam").
- **Builds**: increase effect speed or chase rate every 2–4 bars, or step intensity up.
- **Drops/accents**: a cue exactly on the accent time with fade 0; optionally a blackout cue
  one beat (or half a beat) before.
- **Per-beat chases** only in high-energy sections and only for a few bars at a time;
  alternate fixture groups (odd/even, left/right). Use exact `beat_times`.
- **Fades**: calm sections 1–3 s; energetic sections 0–0.2 s; never longer than the gap to
  the next cue.
- Keep cue count reasonable: ~1 cue per 4–8 bars plus accents, more for chases.
- Last cue: fade out to 0 on the final bar / end of the song.

## 4. Build it

`ma_build_cuelist(sequence, cues, name, executor, song_path, replace)` with
```json
[
  {"time": 0.54, "label": "Intro", "fade": 3,
   "commands": ["Fixture 101 Thru 108", "At 30",
                "Attribute \"ColorRGB1\" At 0", "Attribute \"ColorRGB2\" At 0",
                "Attribute \"ColorRGB3\" At 100"]},
  {"time": 15.53, "label": "Build", "fade": 0.5,
   "commands": ["Fixture 101 Thru 108", "At 80", "At Effect 9",
                "PresetType \"Color\"", "EffectBPM 128"]}
]
```
- `time` = seconds from song start (from the analysis). The tool turns it into Go for cue 1
  and Time triggers (seconds after the previous cue) for every following cue.
- Each cue starts from `ClearAll`, and tracking is off by default, so every cue must contain
  the **complete look** (intensity + colour + effects of all fixtures that should be on).
- Commands are plain grandMA2 command-line syntax; avoid `cd /` inside cue commands.
- Check the returned text for `FEHLER` lines and fix those cues (rebuild with `replace=True`).

## 5. Play, check, save

- `show_play(sequence)` plays the song on this PC and fires Go on the executor exactly at
  the first cue; `show_play(sequence, start_at=60)` starts mid-song (jumps to the right cue).
- `show_status(sequence)` shows song position + current cue; `show_stop(sequence)` stops.
- On a real console the user can instead start the song and press Go on the executor at the
  first cue time.
- Save only when the user agrees: `ma_command('SaveShow "<name>"')`.

## Safety

Never run `Delete`, `NewShow`, `LoadShow`, `Shutdown`, `Reboot` or overwrite an existing
sequence/executor without asking the user first.
