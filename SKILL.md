---
name: karaoke-subtitles
description: Burns word-by-word karaoke subtitles into an English-language video. Each word turns from white to green and briefly scales up as it is spoken. Optionally adds short inline Simplified Chinese glosses, in blue, for technical terms, hard words, phrasal verbs and idioms, pitched at Chinese learners around the CET-6 level (China's College English Test Band 6, upper-intermediate). Use when the user gives an English video file or URL (YouTube, X, or any site yt-dlp supports) and wants word-synced karaoke subtitles, highlighted captions, or English subtitles with Chinese glosses. Needs an Alibaba Cloud Model Studio (DashScope) API key; no storage bucket is needed.
license: MIT (bundled font under SIL OFL 1.1, see assets/fonts/LICENSE.txt)
compatibility: Linux or macOS with a shell, Python 3.9+, ffmpeg built with libass and libx264, yt-dlp for URL input, network access to Alibaba Cloud Model Studio (DashScope), and a DashScope API key (Beijing or Singapore region).
metadata:
  version: "1.2.0"
---

# Karaoke subtitles

Pipeline: video → 16 kHz audio → DashScope ASR with word timestamps → LLM picks terms and writes Chinese glosses → ASS karaoke subtitles → ffmpeg and libass burn-in.

All work goes through one non-interactive CLI, `scripts/pipeline.py`. Paths in this file are relative to the skill directory. Run every command from any directory, with the skill path in front, for example `python3 /path/to/karaoke-subtitles/scripts/pipeline.py doctor`.

## Before the first run

1. Run `python3 scripts/pipeline.py doctor`. Exit 0 means ready. When a key is set, it makes one free request to check that `DASHSCOPE_BASE` matches the key's region. Nothing is uploaded or billed. Add `--offline` to skip that request.
2. If it exits 3, run `bash scripts/install.sh` and fix each `FAIL` row it prints. If the script says sudo needs a password, or the API key is missing, stop and ask the user. Never ask the user to paste the key into the chat; ask them to put it in `.env` (see `.env.example`).
3. Setup details and settings: `references/prerequisites.md`.

## Confirm with the user

- The video: a local file or a URL. The user must have the right to process it.
- Glosses on (default) or off (`--no-annotate`).
- Where the result goes. Default: return the output file path.

Keep the visual style as it is unless the user asks for a change. Style values: `references/ass-style.md`.

## Run

One command runs everything and resumes after an interruption:

```bash
python3 scripts/pipeline.py all "<url-or-file>" --work ./job [--no-annotate]
```

Or run the steps one by one. Each step writes fixed file names in the job directory and skips work whose output already exists. Add `--force` to redo one step. Every subcommand has `--help`.

| Step | Writes | Paid API |
|---|---|---|
| `fetch <url-or-file>` | `src.mp4` | no |
| `transcribe [--audio-url URL]` | `audio.mp3`, `asr_task.json`, `transcription.json` | yes |
| `annotate` | `annotations.json` | yes |
| `ass [--no-pop] [--no-annotate]` | `subs.ass` | no |
| `render [--segment 1200] [--out FILE]` | `karaoke.mp4` | no |

The ASR API reads audio from a URL. By default, `transcribe` uploads `job/audio.mp3` to DashScope's free temporary storage. That storage keeps the file for 48 hours and only this account's ASR model can read it. No bucket or extra setting is needed. If the user prefers their own storage, either `AUDIO_URL_CMD` in `.env` uploads the file and prints a URL, or you pass `--audio-url URL`.

Progress goes to stderr. Each step prints the path of its output on stdout.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Done | Continue. |
| 2 | Usage error | Read the `--help` of the subcommand. |
| 3 | Environment not ready | Follow the `next:` line, or run `doctor`. Ask the user for a key or sudo, or to fix the region setting. |
| 4 | Remote service failed | Follow the `next:` line. Rerunning the same command keeps finished work. |
| 5 | Input from an earlier step missing | Run the step named in the `next:` line. |
| 1 | Unexpected failure | Read the tool output above the error. |

## Long jobs

Transcription and rendering can take longer than a shell tool allows. Run the command in the background with a log file, for example `nohup python3 scripts/pipeline.py all "<src>" --work ./job > job.log 2>&1 &`, then read the log until it ends. If the process dies, run the same command again. Transcription resumes the saved ASR task instead of paying again; rendering reuses finished segments.

## Check before delivery

Extract one frame from the middle of the output (`ffmpeg -ss <seconds> -i job/karaoke.mp4 -frames:v 1 check.jpg`) and look at it if you can view images. If the source already has burned-in captions, tell the user and offer two options: cover them with a blur band, or move the new subtitles to the top.

## Rules

- Never print, log or commit `DASHSCOPE_API_KEY`. `doctor` reports only whether it is set.
- `transcribe` and `annotate` cost money on the user's account. Do not use `--force` on them unless the user agrees.
- Glosses are Simplified Chinese only. For viewers who do not read Chinese, use `--no-annotate`.
- ASR can mishear names and jargon and can return lowercase text. Tell the user to review the subtitles before sharing the video.
