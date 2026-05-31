# ClipLingo

A desktop application that converts videos + subtitles into Anki flashcard decks (.apkg), supporting AI-powered screening & annotation, subtitle transcription, per-clip audio/screenshot extraction, and custom card theming.

## Language

**Card**:
An Anki flashcard, the final output unit. Each card corresponds to one Subtitle that passed AI Screening and AI Annotation. Includes front/back templates, embedded audio and screenshot media.
_Avoid_: Flashcard, Note

**CardStyle**:
The structural layout of a Card's front and back. Two types: **wordcard** (shows a target word on the front with definition + example context) and **sentence** (shows original text on front with translation and notes on back).
_Avoid_: Style, Template layout

**CardTheme**:
A visual styling package comprising HTML templates (front.html, back.html) and CSS. Controls colors, fonts, shadows, spacing for Card rendering. Built-in themes include Default, Minimal, Netflix, Dictionary. Custom themes can be imported as ZIP packages.
_Avoid_: Theme, UI theme, Design

**AI Screening**:
Phase 1 of the two-phase AI workflow. An LLM evaluates each Subtitle and returns include or skip with a reason explaining why it is or isn't worth learning.
_Avoid_: Phase 1, Recommend

**AI Annotation**:
Phase 2 of the two-phase AI workflow. Takes Subtitles that passed AI Screening and generates rich annotations: translation, grammar notes, key vocabulary word, and definition of that word.
_Avoid_: Phase 2, Annotate

**Annotation Purpose**:
A user-facing configuration choice that determines how AI Annotation frames its output: vocab (dictionary-style word annotations) or grammar (syntax-focused grammar notes). Independent of CardStyle selection — both choices are freely combinable.
_Avoid_: Purpose, Mode, Taget purpose

**Subtitle**:
A line of timed text from a video, containing source language text, start second, and end second. Originates from an uploaded .srt file, extracted embedded subtitles, or ASR transcription.
_Avoid_: Sentence, Transcript line

**Deck**:
An Anki deck file (.apkg) containing Cards plus embedded media (audio files, screenshots). Multiple Videos in merge mode produce one combined Deck; in independent mode each Video yields its own Deck.
_Avoid_: Package, Output, Study pack

**Task**:
A single user operation that may contain multiple video files and optionally one subtitle file. Tracks stateful progress through screening → annotation → generation via a UUID.
_Avoid_: Job, Operation, Run

**Learned Word**:
A vocabulary word that has appeared on any generated Card, regardless of target language. Used during AI Screening to filter out already-mastered vocabulary. Stored locally in SQLite.
_Avoid_: Known word, Mastered word

**Card Padding**:
Small millisecond offsets applied around a Subtitle's time range when cutting audio via FFmpeg, preventing abrupt cut-offs. Has padding_start_ms and padding_end_ms components.
_Avoid_: Buffer, Pre-roll

**ASR Engine**:
A pluggable speech-to-text backend. Supported engines are Faster Whisper (local model inference) and Bcut (cloud-based Bilibili API).
_Avoid_: Transcription engine, Speech engine

**Machine Translation**:
A fallback translation service (Bing or Google) available without an AI API key. Produces only basic translation output — no grammar notes, no keyword extraction. Operates with seven-day disk caching.
_Avoid_: Fallback translation, Auto-translate

**Custom Prompt**:
A user-editable system prompt replacing default criteria for AI Screening and AI Annotation phases. Preset options: "Grammar & Sentence Patterns" and "Vocabulary". Supports {source_language} and {target_language} placeholders.
_Avoid_: System prompt, LLM instruction, Model prompt

**Template**:
The HTML structure for a Card's front or back, always referenced through a CardTheme. Themes bundle front and back templates together with style.css.
_Avoid_: Layout, Component, View template
