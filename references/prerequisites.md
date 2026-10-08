# Prerequisites and settings

## Accounts

| Item | Why | How |
|---|---|---|
| Alibaba Cloud Model Studio (DashScope) API key | ASR and the gloss LLM | Create a key in the Model Studio console: the China (Beijing) console at https://bailian.console.aliyun.com, or the international (Singapore) console. Make sure the models in `references/dashscope-api.md` are enabled for the key. |
A storage bucket is not needed. The file-transcription API reads audio from a URL. By default, `transcribe` uploads the audio to DashScope's free temporary storage and passes the resulting `oss://` URL. The file is kept for 48 hours and only your account's ASR model can read it. Your own storage is optional. Use `AUDIO_URL_CMD` with Alibaba Cloud OSS, Amazon S3 or any storage that gives a public or presigned link valid for at least 30 minutes, or pass `--audio-url`.

Regions:
- Beijing and Singapore keys are different. `DASHSCOPE_BASE` must match the key's region. `doctor` checks this with one free request.
- Alibaba Cloud lists both ASR models for both regions.
- The skill was tested end to end in Beijing.
- In Singapore, the temporary-storage upload is not tested. If it fails there, set `AUDIO_URL_CMD`.
- The US (Virginia) region does not offer the file-transcription models, so the skill cannot run there.

## Settings

The CLI reads environment variables first, then `.env` in the skill directory. Copy `.env.example` to `.env` to start. Never commit `.env`.

| Variable | Required | Meaning |
|---|---|---|
| `DASHSCOPE_API_KEY` | yes | DashScope API key. |
| `DASHSCOPE_BASE` | no | API endpoint. Default `https://dashscope.aliyuncs.com` (Beijing). Singapore: `https://dashscope-intl.aliyuncs.com`. It must match the key's region. |
| `AUDIO_URL_CMD` | no | Optional. Shell command that uploads the file given as `$1` and prints its URL. Use it to replace the default DashScope temporary storage with your own storage. Examples are in `.env.example`. |

## Machine

- Linux or macOS, Python 3.9 or later.
- Free disk space of about 3 times the video size.
- No GPU. Rendering runs on the CPU.
- Network access to the DashScope endpoint and, for URL input, to the video site.

Measured in two runs on 2026-10-08 with a 58-second 1080p30 clip on a shared 8-vCPU cloud machine, Beijing region:
- ASR server time: about 3 s. Wall time: 18 s, including the upload and the 10 s poll interval.
- Glosses: 7 to 8 s.
- Rendering: about 13 s, 4.4 to 4.5 times realtime.

Long videos were not measured. Times depend on the CPU, the resolution and the service load.

## Software

`scripts/install.sh` installs these with Homebrew (macOS), apt or dnf (Linux), and pipx or a private venv for yt-dlp. It ends by running `pipeline.py doctor`.

- ffmpeg and ffprobe built with libass and libx264.
- yt-dlp, only for URL input.
- fontconfig. The CJK font Noto Sans CJK SC Bold is bundled in `assets/fonts`.

## Cost

DashScope ASR and `qwen-plus` are pay-as-you-go on the user's own account. Check current prices and any free quota in the Model Studio console. All other steps run locally.
