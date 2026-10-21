# grandma2-mcp — notes for Claude

MCP server that lets Claude Code control grandMA2 (onPC or console) over Telnet and build
song-synchronised light shows.

## Installing on a new PC (when the user asks to "install" this repo)

1. Check prerequisites: grandMA2 onPC installed (`C:\Program Files\MA Lighting Technologies\grandma`),
   Python 3.10+ (`py -3 --version`), Claude Code CLI (`claude --version`).
2. Run `powershell -ExecutionPolicy Bypass -File install.ps1` from the repo root
   (options: `-GmaHost`, `-GmaPort`, `-GmaUser`, `-GmaPassword`, `-SkipShow`).
3. Tell the user to start onPC, load show `claude_base` (or enable Telnet "Login Enabled" in
   Setup → Console → Global Settings) and open a new Claude Code session.
4. Verify in the new session with `ma_status` and `ma_command("List Fixture")`.

## Layout

- `server.py` — MCP server (Telnet client, MA tools, patch, cue-list builder, playback tools)
- `audio.py` — song analysis (librosa) and synced playback (sounddevice)
- `skills/grandma2-lightshow/SKILL.md` — workflow for song → light show
- `shows/claude_base.show.gz` — empty grandMA2 3.9.61 show with Telnet login enabled
- `examples/make_test_song.py` — synthetic 128 BPM test track with known structure

## grandMA2 command-line facts verified with onPC 3.9.61

- Telnet port 30000 = command line (`Login "administrator" "admin"`), 30001 = read-only system monitor.
  "Remote commandline disabled" → Telnet login is off in Global Settings.
- `;` chains commands, but `cd /` only works as a command on its own.
- In `EditSetup/Layers/<n>`: `Store 1 Thru 8`, `Assign FixtureType 4 At 1 Thru 8`, then one option per
  `Assign`: `/fixid=101`, `/patch="1.1"`, `/name="Wash 1"` (combined options are ignored; `/fixid` resets the name).
- Fixture types: `cd EditSetup; cd FixtureTypes; Import "generic@led_-_rgbw@8_bit" At 4`.
- Cue timing: `Assign Sequence 10 Cue 2 /trig=time /trigtime=2.5 /fade=1` (trigtime = seconds after previous cue).
- Tracking off: `Assign Sequence 10 /track=off`. Effects: `At Effect 9`, then `PresetType "Color"; EffectBPM 128`.
- `gma.show.getdmx()` returns 0 on onPC without output hardware; use `gma.show.getvar("SELECTEDEXECCUE")`
  after `Select Executor x.y` to read the running cue.
