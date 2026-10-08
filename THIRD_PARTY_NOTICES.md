# Third-party notices

The code in this repository is under the MIT License (`LICENSE`). This file covers the parts that are not.

## Bundled

| Component | License | Source |
|---|---|---|
| Noto Sans CJK SC Bold, `assets/fonts/NotoSansCJKsc-Bold.otf` | SIL Open Font License 1.1. Full text: `assets/fonts/LICENSE.txt`. | https://github.com/notofonts/noto-cjk |

## Called, not bundled

The user installs these tools separately; `scripts/install.sh` uses Homebrew, apt, dnf or pipx. Each tool stays under its own license. The license column quotes what each project states.

| Tool | Used for | License | Source |
|---|---|---|---|
| FFmpeg (`ffmpeg`, `ffprobe`) | Audio extraction, burn-in, joining segments | LGPL 2.1 or later. Optional parts are GPL 2 or later; if a build uses them, the GPL applies to all of FFmpeg. The render step needs libx264, which is one of those GPL parts. | https://ffmpeg.org/legal.html |
| x264 (`libx264`) | H.264 encoding inside FFmpeg | GPL 2 or later | https://www.videolan.org/developers/x264.html |
| libass | ASS subtitle rendering inside FFmpeg | ISC | https://github.com/libass/libass/blob/master/COPYING |
| fontconfig | Font lookup for libass | Permissive license, see COPYING | https://gitlab.freedesktop.org/fontconfig/fontconfig/-/blob/main/COPYING |
| yt-dlp | Downloading videos from URLs | Unlicense for the git repository and the PyPI packages. The PyInstaller-bundled release executables include GPLv3+ code. | https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE |
| Python | Runs `scripts/pipeline.py` | Python Software Foundation License Version 2 | https://docs.python.org/3/license.html |

## Remote service

`transcribe` and `annotate` send audio and subtitle text to Alibaba Cloud Model Studio (DashScope), which runs the ASR models and `qwen-plus`. No Alibaba Cloud code is in this repository. Use of the service is governed by Alibaba Cloud's agreements and is billed to the user's own API key:

- International site: https://www.alibabacloud.com/help/en/model-studio/related-agreements
- China site: https://help.aliyun.com/zh/model-studio/related-agreements
