# AGENTS.md

This directory is an Agent Skill. The full instructions are in `SKILL.md`. Read it before you run anything.

Short version for agents that do not load skills:

- Check the setup with `python3 scripts/pipeline.py doctor`. It costs nothing. With a key set, it makes one free request to check the key's region. `--offline` skips that request.
- Run `python3 scripts/pipeline.py all "<url-or-file>" --work ./job`. The output is `job/karaoke.mp4`.
- Every subcommand has `--help`. Rerunning a command resumes it. `SKILL.md` lists the exit codes.
- `transcribe` and `annotate` call a paid API on the user's key. Do not add `--force` to them without the user's consent.
- Never print or commit `DASHSCOPE_API_KEY`.
