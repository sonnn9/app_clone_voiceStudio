# AudioStudio Batch TTS

A Windows desktop app (PySide6) that turns TXT scripts – single files or whole
folder trees – into MP3/WAV/FLAC audio using your **local AudioStudio
(VoiceStudio) server**. No cloud TTS is used.

Daily workflow:

1. Start AudioStudio.
2. Open **AudioStudio Batch TTS** – it connects automatically.
3. Choose a **Profile**.
4. Click **Select Folder** – every `*.txt` in the folder and all subfolders is queued.
5. Check the detected **Story / Conversation** modes.
6. Click **Start** – `story1.txt` becomes `story1.mp3` in the same folder.
7. Failed files can be retried without regenerating finished ones.

---

## Installation (development)

Requirements: Windows 10/11, Python **3.11+** (3.13 tested), ffmpeg for MP3/FLAC.

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python main.py
```

ffmpeg: `winget install Gyan.FFmpeg`, or put `ffmpeg.exe` next to the EXE, or
set its path in **Settings → Output → ffmpeg**. Without ffmpeg only WAV output
is possible (the app says so clearly).

## Connecting to AudioStudio

1. Start AudioStudio (the VoiceStudio desktop app or its backend).
2. **Settings → AudioStudio server → API Base URL** – enter the address the
   backend listens on, e.g. `http://127.0.0.1:3900` (VoiceStudio's default
   port; check `GET /system/info → backend_port` if you changed it), or press
   **Detect** (tries the addresses listed in `app/resources/default_settings.json`).
3. Press **Test Connection** → *Connected* / *Not Connected*, plus version,
   device, GPU/VRAM, active engine and model status.

Timeout, retry count and increasing retry delays (default 1 s, 3 s, 5 s) are
configurable. GPU out-of-memory errors are *not* retried endlessly – the app
suggests lowering concurrency, restarting the backend or using shorter chunks.

The API findings (endpoints, request fields, limits) are documented in
[docs/API_FINDINGS.md](docs/API_FINDINGS.md). Quick CLI check without the GUI:

```bat
python test_tts.py --url http://127.0.0.1:3900 --list-models --list-voices
python test_tts.py --url http://127.0.0.1:3900 --voice archetype:feat_00_the_librarian --text "Hello!"
```

## Voices

Voices are loaded live from AudioStudio – nothing is hard-coded:

* **My profiles** – voice profiles saved/cloned in AudioStudio (`GET /profiles`).
* **Designed voices** – the ~1 100 AudioStudio archetypes with gender, age,
  pitch, accent, language and category (`GET /archetypes`). They are generated
  through AudioStudio's voice design prompt; a fixed seed keeps the voice
  consistent across chunks. *Save designed voice as AudioStudio profile* makes
  the identity fully fixed.
* **Engine default**.

The **Voices** page filters by gender, language, category and source, and
previews any voice (Play / Stop / Replay). Preview files are temporary and
cleaned automatically.

Only what the API supports is shown: there are no emotion/pitch/volume/
temperature controls because AudioStudio's speech API has no such fields.
Engine-specific parameters (e.g. OmniVoice *Quality steps*, *Guidance scale*)
are read from the server's own OpenAPI schema and appear only for engines that
support them. Unsupported parameters are never sent.

## Profiles

**Profiles** stores reusable presets (`%APPDATA%\AudioStudioBatchTTS\profiles.json`):
engine, default mode, narrator voice, speaker → voice mapping, speed, language,
style instruction, engine parameters, pauses, profile pronunciation rules and an
optional output-format override. New / Duplicate / Delete / Save.

Example profiles are included (Story – Female Narrator, Story – Male Narrator,
English Lesson, Kids Story, Conversation Male/Female, News Reading, Slow
English Practice).

## Story TXT format

Plain text. Blank lines separate paragraphs.

```
Once upon a time, there was a small rabbit...

One day, she found a tiny blue bird.
```

The whole story uses the narrator voice. Long text is split into chunks
(paragraph → sentence → punctuation → whitespace; never inside a word), each
chunk is generated separately and merged into one file. Pauses between
paragraphs (and optionally sentences) are configurable per profile.

## Conversation TXT format

```
[NARRATOR]
Today we are going to learn about travelling.

[ANNA]
Hi Tom! Where did you go last weekend?

[TOM]
I went to Da Nang with my family.
```

or

```
Anna: Hello.
Tom: Hi Anna.
```

Speakers are detected automatically (Vietnamese names work too, e.g.
`[CÔ GIÁO]`). Map each speaker to a voice in the profile (*Detect from TXT
file…* fills the list); unmapped speakers use the narrator voice. Pauses:
between turns (default 300 ms), between paragraphs (600 ms), before narrator
sections (configurable).

**Auto** mode picks Conversation when speaker tags are found, otherwise Story;
you can override per file (right-click → *Set mode*) or for the whole batch.

New dialogue syntaxes can be added by subclassing `DialogueFormat` in
`app/parsers/conversation_parser.py`.

## Batch folder processing

* **Select Folder** (or drag & drop folders/TXT files onto the window) scans
  recursively. The queue shows File, Folder (relative path), Mode, Profile,
  Voices, Duration, Progress, Status and Error.
* Check/uncheck files, *Select all / none / failed*, *Remove selected*,
  *Retry selected*, filter by file name, status and mode.
* Double-click a row to see the original text, the processed text, the
  detected speakers, their voices and the exact segments.
* **Start / Pause / Resume / Cancel / Retry failed**. The UI stays responsive;
  all generation runs in worker threads. *Concurrent jobs* (1–4, default 1) –
  more jobs use more GPU memory.
* Output: **Same folder as TXT** (default) or **Custom folder** that mirrors
  the source subfolders.
* If the output already exists: **Skip** (default), Overwrite, Ask, or
  Generate with suffix (`story1_001.mp3`).
* Unicode file names are kept (`Bài đọc số 1.txt` → `Bài đọc số 1.mp3`); only
  characters Windows forbids are replaced.
* After the batch a summary is shown and **batch_report.csv** can be exported
  (File, input/output path, voice, model, status, error, processing time).

### Safety, resume and cache

* Audio is first written as `story1.mp3.part` and atomically renamed – a
  cancelled or crashed run never leaves a broken MP3.
* Segments are generated into `%APPDATA%\AudioStudioBatchTTS\work\<job>` and
  only merged when all succeeded. A retry reuses the segments that were
  already generated.
* The queue is saved every few seconds. After a crash or restart the app
  offers to restore the unfinished batch; completed files are not regenerated.
* **Audio cache** (on by default): identical text + voice + model + parameters
  reuse the cached segment. *Settings → Clear Cache*.

### Per-folder settings (`tts_config.json`)

Put a `tts_config.json` into any folder; files there (and in subfolders,
unless they have their own config or you disable inheritance) use it:

```json
{
  "profile": "English Lesson",
  "mode": "conversation",
  "voice": "profile:demo0001",
  "speaker_voices": {
    "ANNA": "archetype:feat_04_the_neighbor",
    "TOM":  {"key": "archetype:feat_06_the_mate", "name": "The Mate",
             "instruct": "male, young adult, moderate pitch, australian accent"}
  },
  "speed": 0.9,
  "language": "en",
  "silence": {"turn_ms": 400, "paragraph_ms": 800},
  "output_format": "mp3",
  "inherit_parent": true
}
```

Voice keys are shown in the Voices page (*Voice ID*): `profile:<id>`,
`archetype:<id>` or `default`. For archetypes, include `instruct` (as above)
so the voice design is known even before the voice list is loaded.

## Text preprocessing & pronunciation

Before sending text the app can trim duplicate spaces, normalise line endings,
remove extra blank lines and convert curly quotes – never changing meaning.
The TXT files themselves are never modified.

**Pronunciation** rules (`WSC → World Scholar's Cup`, `PECC1 → P E C C One`)
can be global (Pronunciation page) or per profile; whole-word and case
options are available.

## Output

* MP3 (default, 128/192/256/320 kbps), WAV or FLAC. AudioStudio returns
  lossless WAV and the app encodes locally. AudioStudio voices are 24 kHz mono,
  for which the MP3 standard allows at most 160 kbps – higher settings are
  encoded at 160 kbps.
* Optional gentle loudness normalisation (EBU R128, linear gain – no
  compression).
* Optional tags: Title = TXT name, Comment = generator.

## App data

Everything editable lives in `%APPDATA%\AudioStudioBatchTTS\`
(settings, profiles, pronunciation, logs, cache, session, work). *Settings →
Open App Data Folder*, *Logs → Open Logs Folder*. Logs: `logs\app.log`
(rotating) and `logs\batch_YYYY-MM-DD.log`. Text content is not logged.

## Building the EXE

```bat
build.bat
```

or

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1            # build
powershell -ExecutionPolicy Bypass -File build.ps1 -BundleFfmpeg  # also copy ffmpeg.exe from PATH
```

Result: `dist\AudioStudioBatchTTS.exe` – a portable single-file app. To ship
ffmpeg, place `ffmpeg.exe` in `.\ffmpeg\` before building (or use
`-BundleFfmpeg`); it is copied next to the EXE and found automatically. Use an
LGPL/GPL ffmpeg build according to its license.

## Tests

```bat
python -m pytest -q tests
```

Covers recursive scanning, Unicode file names, encodings, story/conversation
parsing, speaker detection, chunk splitting, segment planning and pauses,
output paths (same folder / custom folder with subfolders), skip/suffix
behaviour, pronunciation rules, preprocessing, cache keys, folder configs,
capability filtering, request building, OOM detection and WAV merging.

## Project structure

```
main.py                 entry point (python main.py)
test_tts.py             CLI adapter test
app/
  main.py               bootstrap (logging, Qt, theme)
  api/                  BaseTTSAdapter, AudioStudioAdapter, errors, registry
  core/                 settings, profiles, jobs, batch manager, job processor,
                        session, cache, folder config, output paths, report
  parsers/              story / conversation parsers, auto-detect
  audio/                ffmpeg, WAV merger, converter, metadata
  utils/                file scanner, text splitter, text IO, logger, paths
  ui/                   main window, pages, widgets, theme
  resources/            default settings, example profiles, icon
samples/                example story / conversation / nested lesson folders
tests/                  pytest suite
docs/API_FINDINGS.md    AudioStudio API inspection results
```

Adding another local engine later (Kokoro, XTTS, F5-TTS …) means implementing
`BaseTTSAdapter` and registering it in `app/api/registry.py`; the batch
engine, parsers and UI do not change.

## Troubleshooting

| Problem | Fix |
|---|---|
| *Not Connected* | Start AudioStudio; check the URL/port; press Test Connection. A firewall/proxy is bypassed for local requests. |
| *Timeout* on the first file | The model is loading. Wait until AudioStudio shows the model ready, or raise the timeout. |
| *GPU out of memory* | Set Concurrent jobs to 1, restart the AudioStudio backend, lower *Max characters per chunk*. |
| *ffmpeg was not found* | Install ffmpeg or set its path in Settings, or choose WAV. |
| *Cannot decode file* | Save the TXT as UTF-8 (UTF-8 BOM and UTF-16 also work). |
| A file was skipped | Its output already exists and *If output exists* = Skip. Choose Overwrite or Suffix. |
| Voice sounds different between chunks | Use a saved profile voice (or *Save designed voice as AudioStudio profile*). |
| Speakers not detected | Use `[NAME]` on its own line or `Name: text`; check the Preview dialog. |
