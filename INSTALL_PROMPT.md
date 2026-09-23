# One-line agent-prompt install

Copy-paste this to any AI assistant (Hermes, Claude, GPT, Gemini). It does the whole setup itself — no shell one-liner required.

```text
Install AnkiTutor into ~/.anki-tutor from
https://github.com/MarionLiew/anki-tutor . Clone it, create the state/ and
library/ subdirs, pip install -r requirements.txt, then verify with:
    cd ~/.anki-tutor && python3 src/cli.py health
"OK" means AnkiConnect on localhost:8765 answers 6. If Anki isn't running,
just say so — do not touch any of my existing files, keys, or data.
```

## Why a prompt, not a script

The agent prompt is the modern install. The assistant already owns your terminal, knows your environment, and can adapt the steps (wrong Python, missing Anki, existing dir). A `curl | bash` one-liner is brittle across machines and needs its own uninstall story. Keep both: the prompt for everyday use, [install.sh](install.sh) for the scripted path.