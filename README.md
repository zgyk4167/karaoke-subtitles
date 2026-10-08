# karaoke-subtitles

Subtitles that follow the speaker word by word, for people who are learning English or who find spoken English hard to follow.

Each word turns from white to green as it is spoken and briefly grows, so the eye can stay with the voice. For Chinese speakers, harder words, technical terms, phrasal verbs and idioms can get a short Simplified Chinese gloss in blue, right after the word. The glosses are pitched at about the CET-6 level (China's College English Test Band 6, upper-intermediate). They explain single terms, so the subtitle line stays in English.

If you do not read Chinese, add `--no-annotate`. You get plain English subtitles with the word-by-word highlight and nothing else.

This is an Agent Skill in the open [Agent Skills](https://agentskills.io/specification) format. All of its work runs through one command-line script, so any agent that can run a shell command can use it.

## Why word by word

Captions in the language being spoken are well studied in language learning. A 2013 meta-analysis of 18 studies found that learners who watched second-language video with captions in that language scored higher on listening comprehension and vocabulary tests than learners who watched without captions ([Montero Perez, Van Den Noortgate & Desmet, *System* 41(3)](https://doi.org/10.1016/j.system.2013.07.013)). The authors note that the number of studies was limited.

A related idea is Same Language Subtitling in India: film songs on TV are subtitled in the language that is sung. Its authors describe highlighting the words in time with the song as a way to match text and sound. After five years of Hindi film songs subtitled this way on national TV, regular viewers showed greater gains in reading skills than viewers who rarely watched ([Kothari & Bandyopadhyay, *ITID* 10(4), 2014](https://itidjournal.org/index.php/itid/article/view/1307.html)).

Neither study tested this tool. The second one is about reading in one's own language, not listening in a second language. The word-by-word highlight here is a design choice. For the author, it makes it easier to keep up with the pace of fast speech.

## How it works

1. `fetch`: download the video with yt-dlp, or copy a local file.
2. `transcribe`: get word-level timestamps from Alibaba Cloud Model Studio (DashScope) ASR.
3. `annotate`: `qwen-plus` picks the terms worth a gloss and writes a 2 to 8 character Chinese gloss for each. It glosses the term, never the whole sentence.
4. `ass`: build an ASS subtitle file with per-word karaoke timing and the pop effect.
5. `render`: burn the subtitles into the video with ffmpeg and libass.

Add `--no-annotate` to skip step 3 and get plain karaoke subtitles with no Chinese.

## Quick start

```bash
bash scripts/install.sh          # installs ffmpeg, yt-dlp; ends with a readiness check
cp .env.example .env             # set DASHSCOPE_API_KEY (and DASHSCOPE_BASE for a Singapore key)
python3 scripts/pipeline.py doctor   # checks tools and the key's region; free
python3 scripts/pipeline.py all "<video-url-or-file>" --work ./job
# result: ./job/karaoke.mp4
```

The transcription API reads audio from a URL. By default, the script uploads the extracted audio to DashScope's free temporary storage, where it is kept for 48 hours. You do not need a bucket. To use your own storage instead, set `AUDIO_URL_CMD` (`.env.example` has OSS and S3 examples) or pass `--audio-url`.

## Measured run

Two test runs on 2026-10-08:
- Input: a 58-second 1080p30 clip.
- Setup: Beijing region, on a shared cloud machine with 8 vCPUs.
- Total time: 38 to 40 seconds.
- Speech recognition: about 3 seconds of server time (18 seconds wall time, including upload and polling).
- Glosses: 7 to 8 seconds.
- Rendering: about 13 seconds, 4.4 to 4.5 times realtime.

Times depend on the machine, the video and the service load.

## Known limits

- Speech recognition can mishear names and jargon and can return lowercase text. Review the subtitles before you share the video.

Requirements, settings and cost: [`references/prerequisites.md`](references/prerequisites.md). CLI steps and exit codes: [`SKILL.md`](SKILL.md).

## Adapt it to another language

The skill is built for English audio with optional Simplified Chinese glosses. Other language pairs are not supported out of the box. One example is Spanish audio with English glosses, for an English speaker learning Spanish. You can try adapting a fork. These are the places to change in `scripts/pipeline.py`:

1. **Spoken language.** In `submit_asr`, change `"language_hints": ["en"]` to the language of the audio, for example `["es"]`. Check Alibaba Cloud's model documentation for that language. It must be supported, and the ASR result must include word timestamps. Only English has been tested with this skill.
2. **Gloss language and level.** Rewrite `ANNOTATE_PROMPT` for your learners: who they are, which items to mark, the gloss language and the gloss length. The reply format stores each gloss under the key `"zh"`. Either keep that key, or rename it in both the prompt and `cmd_ass` (`item["zh"]`).
3. **Line length.** `MAXW` (7 words) and `MAXC` (42 characters) are tuned for English. Adjust them if words in the spoken language are longer.
4. **Font.** The bundled Noto Sans CJK SC covers Chinese and Latin script. Its character map includes Spanish and Western European accented letters such as á, ñ, ü, ¿, ç and ß; rendering them was not tested. For other scripts, bundle a font that covers them. Then change `FONT_FILE` and the font name in the `Style:` line of `HEADER`.
5. **Word splitting.** `load_lines` assumes words are separated by spaces. A token without a leading space is merged into the previous word. Languages written without spaces need a different line builder.

Run the whole pipeline on a short clip first, and check the timing and glosses before longer videos.

## Use with your agent

Copy or clone this folder, named `karaoke-subtitles`, into one of the skill directories your agent loads:

| Agent | Project directory | Personal directory | Source |
|---|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` | [docs](https://docs.claude.com/en/docs/claude-code/skills) |
| OpenAI Codex | `.agents/skills/` | `~/.agents/skills/` | [docs](https://developers.openai.com/codex/skills) |
| Cursor | `.agents/skills/` or `.cursor/skills/` | `~/.agents/skills/` or `~/.cursor/skills/` | [docs](https://cursor.com/docs/context/skills) |
| Gemini CLI | `.agents/skills/` or `.gemini/skills/` | `~/.agents/skills/` or `~/.gemini/skills/` | [docs](https://geminicli.com/docs/cli/skills/) |
| GitHub Copilot (cloud agent, CLI, VS Code and JetBrains agent mode) | `.github/skills/`, `.claude/skills/` or `.agents/skills/` | `~/.copilot/skills/` or `~/.agents/skills/` | [docs](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) |

Cursor also reads `.claude/skills/` and `~/.claude/skills/`. One copy in `~/.agents/skills/` therefore covers Codex, Cursor, Gemini CLI and Copilot, and one in `~/.claude/skills/` covers Claude Code and Cursor.

For an agent without skill support, point it at [`AGENTS.md`](AGENTS.md) or `SKILL.md`, or just run the commands in Quick start.

## Responsible use

- Process only videos you have the right to use, and share the output only where you have that right.
- Downloading with yt-dlp must follow the terms of the site you download from.
- `transcribe` and `annotate` send the audio and the subtitle text to Alibaba Cloud. By default the audio is stored in DashScope's temporary storage for 48 hours. That use falls under Alibaba Cloud's terms and is billed to your own API key.

## License

Code: MIT, see [`LICENSE`](LICENSE). Bundled font Noto Sans CJK SC: SIL Open Font License 1.1, see [`assets/fonts/LICENSE.txt`](assets/fonts/LICENSE.txt). Tools the skill calls but does not bundle (ffmpeg, libass, x264, yt-dlp) and the DashScope API terms: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
