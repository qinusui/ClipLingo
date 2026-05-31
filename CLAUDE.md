# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ClipLingo converts videos + subtitles into Anki flashcard decks (.apkg). It supports subtitle import, Whisper auto-transcription, AI-based screening & annotation, per-clip audio/screenshot extraction, and Anki package generation.

**Architecture**: Desktop app (PyInstaller single-bundle) with FastAPI backend serving a React SPA, plus CLI entry point for headless usage.

**Tech Stack**:
- Backend: Python 3.13, FastAPI, Uvicorn, OpenAI SDK, Faster-Whisper, ffmpeg, genanki
- Frontend: React 18, TypeScript, Vite, Tailwind CSS, i18next, Axios
- Desktop: PyInstaller → Inno Setup installer

## Commands

### Development

```bash
# Install dependencies (use root .venv)
python -m venv .venv  # if not exists
.venv/Scripts/Activate.ps1  # Windows
pip install -r requirements.txt

# Frontend dev server
cd frontend && npm run dev

# Start all services (frontend + backend together)
python scripts/start-all.py

# Or start backend separately
python scripts/start-backend.bat    # Windows
bash scripts/start-backend.sh       # Unix
```

### Building

```bash
# Build frontend dist
cd frontend && npm run build

# Lint frontend
cd frontend && npm run lint
```

### Testing

```bash
# Run all tests
python -m pytest tests/

# Run backend tests only
python -m pytest tests/backend/

# Run a specific test file
python -m pytest tests/backend/test_whisper.py

# Frontend tests (if any)
cd frontend && npm test
```

### Packaging (Release)

```bash
# 1. Build frontend
cd frontend && npm run build

# 2. PyInstaller bundle (use root .venv, NOT backend/venv)
rm -rf dist/ClipLingo
.venv/Scripts/python.exe -m PyInstaller ClipLingo.spec

# 3. Inno Setup installer
iscc installer.iss   # outputs dist/ClipLingo_Setup.exe
```

## Code Architecture

```
ClipLingo/
├── main.py                    # CLI entry: run(), generate_apkg() — orchestrates full pipeline
├── errors.py                  # Unified ErrorCode enum + translate_error() exception mapping
├── backend/main.py            # FastAPI app: lifespan, CORS, static files, health, routes
├── backend/api/               # REST API routers
│   ├── subtitles.py           # Upload / parse / list subtitles
│   ├── process.py             # Trigger media processing (FFmpeg cut/snapshot), progress tracking
│   ├── cards.py               # Card list / style selection / package generation
│   ├── themes.py              # Theme listing / import / preview
│   ├── annotate.py            # Two-phase AI annotation endpoints
│   ├── style_generator.py     # Generate card CSS styles via AI
│   └── translate.py           # Standalone translation endpoint
├── backend/models/schemas.py  # Pydantic request/response schemas
├── backend/services/progress.py  # Task progress state management
├── core/                      # Business logic layer (independent of framework)
│   ├── parse_srt.py           # SRT parser: Subtitle dataclass, filter_short_subtitles
│   ├── ai_process.py          # AIProcessor: batch calling OpenAI-compatible API, two-phase screen+annotate
│   ├── media_cut.py           # FFmpeg wrapper: parallel audio slicing + screenshot extraction
│   ├── pack_apkg.py           # Anki deck creation via genanki
│   ├── model_downloader.py    # Whisper model file download
│   ├── templates.py           # Card HTML template rendering
│   ├── whisper_manager.py     # Model caching/lifecycle
│   ├── whisper_runner.py      # Transcription execution
│   ├── whisper_transcribe.py  # Save segments to SRT format
│   ├── asr/                   # ASR engine abstraction
│   │   ├── base.py            # BaseASREngine interface
│   │   ├── whisper_engine.py  # Faster-Whisper implementation
│   │   └── bcut_engine.py     # Bilibili BCut cloud ASR
│   └── translate/             # Translation service abstraction
│       ├── base.py            # BaseTranslator interface
│       ├── bing.py            # Microsoft Translator
│       └── google.py          # Google Translate
├── frontend/src/              # React SPA
│   ├── App.tsx                # Main layout + state machine (step 1→2→3)
│   ├── components/            # UI: FileUpload, ProcessingStatus, CardPreview, SubtitleTable, etc.
│   ├── hooks/useTheme.ts      # Theme context provider
│   ├── services/api.ts        # Axios instance + API call wrappers
│   ├── services/ankiConnect.ts  # AnkiConnect protocol proxy
│   ├── services/syncToAnki.ts   # Background sync to Anki
│   ├── services/themeAPI.ts     # Theme marketplace calls
│   ├── types/index.ts         # TypeScript interfaces matching backend schemas
│   └── i18n/index.ts          # Multilingual support (zh/en)
├── scripts/                   # Startup helpers
└── tests/backend/             # pytest suite (see Testing section)
```

## Key Files

| File | Purpose |
| ---- | ------- |
| `main.py` | CLI orchestration: video→subtitle→AI→media→package pipeline; supports single/multi-video merge or independent modes |
| `backend/main.py` | FastAPI entry: registers all routers, handles frozen/dev path resolution, heartbeat/shutdown/update-check endpoints |
| `errors.py` | Centralized error codes: every business error maps to `ErrorCode` enum; `translate_error(exc)` extracts code from raw exceptions |
| `core/ai_process.py` | Two-phase AI: Phase 1 screens (include/skip), Phase 2 annotates (translation + notes); configurable system prompts |
| `core/media_cut.py` | Parallel FFmpeg audio cuts + screenshot grabs via ThreadPoolExecutor |
| `core/pack_apkg.py` | Reads processed card dicts → generates .apkg using genanki with custom HTML templates |
| `core/asr/base.py` | Abstract base class defining `transcribe()` interface for ASR engines |
| `core/translate/base.py` | Abstract base class defining `translate()` interface for translation backends |
| `backend/api/process.py` | Stateful progress tracking per task (UUID), manages temp dirs under `%APPDATA%/ClipLingo/output/{task_id}/` |
| `frontend/src/App.tsx` | Main UI controller: step-by-step wizard managing upload → config → processing → preview → download lifecycle |

## Frozen Mode Path Rules

When bundled (`sys.frozen = True`), `sys.executable` points to Program Files — **write operations must use `%APPDATA%/ClipLingo/`**.

Files that define writable directories in frozen mode:
- `backend/main.py` — `INSTALL_DIR`
- `backend/api/process.py` — `TEMP_DIR` and `base_output`
- `backend/api/queue.py` — `_INSTALL_DIR` and `_get_base_output()`
- `backend/api/subtitles.py` — `_get_base_dir()` → `_get_temp_dir()`

```python
if getattr(sys, 'frozen', False):
    WRITABLE_DIR = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
```

**Never** write to `Path(sys.executable).parent` or `Path(sys._MEIPASS)` in frozen mode.

Always use `parents=True` when creating directories: `dir_path.mkdir(parents=True, exist_ok=True)`.

## Testing

Backend tests cover: subtitle parsing, media cutting, AI concurrency, ASR engines (Whisper + BCut), translation services (Bing + Google), error handling, themes, annotations.

Run with: `python -m pytest tests/backend/ -v`

Each test function must cover:
- **Normal cases**: valid input, correct output
- **Boundary cases**: empty input, very short/long timelines, special characters
- **Exception cases**: missing files, wrong format — verify proper exception raised

After every feature or bug fix: write a test → run it → confirm green → full test suite.

## Bug Fix Rules

1. **Minimal change**: touch only the smallest scope causing the bug
2. **Reproduce first**: write a test that reproduces the bug before fixing
3. **Verify**: run the test after fixing to confirm it passes
4. **No new changes**: run full test suite after the fix

## Version Release Rules

After every version bump, update `RELEASE_NOTES.md` with the new version's changelog at the top (bilingual zh/en, categorized by Features / Bug Fixes / UX Improvements).

## Forbidden

- No features without tests
- No touching unrelated modules in one change
- No `print()` debugging — use `logging` instead
- No hardcoded paths — use config or environment variables

## Communication & Error Handling

- **Chinese first**: all code explanations, error analysis, and comments must be in Chinese
- When the user pastes a traceback: translate the core meaning of the error in Chinese before analyzing

## Conventions

- Use `logging` instead of `print` for debugging (except `main.py` CLI progress output)
- Commit messages follow Conventional Commits: `feat:`, `fix:`, `test:`
- Keep changes minimal and focused — one feature or fix per commit

## Agent skills

### Issue tracker

Issues are tracked as GitHub issues. Use the `gh` CLI for all issue operations. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix) map directly to tracker labels without overrides. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo: one `CONTEXT.md` at root + `docs/adr/` for architectural decisions. See `docs/agents/domain.md`.
