# DashScope API used by this skill

Alibaba Cloud Model Studio exposes these APIs under the name DashScope.

- Auth header on every call: `Authorization: Bearer $DASHSCOPE_API_KEY`
- Base URL: Beijing `https://dashscope.aliyuncs.com`, Singapore `https://dashscope-intl.aliyuncs.com`
- Official guide (Chinese): https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide
- Alibaba Cloud also offers per-workspace domains (`{WorkspaceId}.cn-beijing.maas.aliyuncs.com`, `{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com`). The domains above still work. With the workspace domains, the filetrans models require a `parameters` object. The CLI always sends one.

## 0. Temporary upload (default audio URL)

Docs: https://help.aliyun.com/zh/model-studio/get-temporary-file-url

```
GET /api/v1/uploads?action=getPolicy&model=<ASR model>
→ {"data": {"upload_host", "upload_dir", "policy", "signature", "oss_access_key_id",
            "x_oss_object_acl", "x_oss_forbid_overwrite", "max_file_size_mb", ...}}
POST <upload_host>  (multipart form: OSSAccessKeyId, Signature, policy, x-oss-object-acl,
                     x-oss-forbid-overwrite, key=<upload_dir>/<file name>, success_action_status=200, file last)
→ audio URL: oss://<upload_dir>/<file name>
```

- The upload and storage are free. The file is kept 48 hours.
- The file is bound to the model named in `getPolicy` and to the uploading account. The CLI therefore uploads again when it falls back to `fun-asr`.
- Files up to 1 GB. The upload-policy endpoint is rate-limited to 100 QPS.
- Every request that passes an `oss://` URL must send `X-DashScope-OssResourceResolve: enable`. The filetrans models accept `oss://` URLs only through the REST API, not the SDK.
- `doctor` calls `getPolicy` once, without uploading anything, to check that the key works with `DASHSCOPE_BASE`.

## Models

| Use | Model | Notes |
|---|---|---|
| ASR | `qwen-audio-3.1-asr-flash-filetrans` | Default (`--asr-model`). |
| ASR fallback | `fun-asr` | Used automatically if submitting with the default model fails. |
| Glosses | `qwen-plus` | Default (`--gloss-model`). |

Do not use `qwen3-asr-flash-filetrans`. Alibaba Cloud scheduled its retirement for 2026-10-10.

## 1. Submit an async transcription

```
POST /api/v1/services/audio/asr/transcription
Headers: Content-Type: application/json, X-DashScope-Async: enable
         (+ X-DashScope-OssResourceResolve: enable when the URL is oss://)
{
  "model": "qwen-audio-3.1-asr-flash-filetrans",
  "input": {"file_urls": ["oss://dashscope-instant/.../audio.mp3"]},   // or any public https URL
  "parameters": {"channel_id": [0], "language_hints": ["en"]}
}
→ {"output": {"task_id": "...", "task_status": "PENDING"}}
```

Limits: up to 12 hours and 2 GB per file. An http(s) URL must be fetchable without login. Word timestamps are on by default.

## 2. Poll

```
GET /api/v1/tasks/{task_id}
→ task_status: PENDING | RUNNING | SUCCEEDED | FAILED
```

On success, the transcription URL is at `output.output.results[0].transcription_url`; some versions use `output.results[0].transcription_url`. The CLI accepts both.

## 3. Result JSON

```
transcripts[0].sentences[]: {begin_time, end_time, text,
  words[]: {begin_time, end_time, text, punctuation, confidence}}
```

Times are in milliseconds. A word whose `text` has no leading space is a sub-word piece of the previous word ("gro" + "k"); the CLI merges it.

## 4. Gloss LLM (OpenAI-compatible)

```
POST /compatible-mode/v1/chat/completions
{"model": "qwen-plus", "temperature": 0.2, "messages": [{"role": "user", "content": PROMPT}]}
```

The prompt is `ANNOTATE_PROMPT` in `scripts/pipeline.py`. The reply must contain a JSON array: `[{"id": <line number>, "term": "<exact words from that line>", "zh": "<short Simplified Chinese gloss>"}]`. Items whose `term` does not match the line are dropped when the ASS file is built.
