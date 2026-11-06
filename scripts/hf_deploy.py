#!/usr/bin/env python3
"""One-command Hugging Face Spaces deploy (Docker mode, free, no card).

Usage:
    HF_TOKEN=hf_xxx python scripts/hf_deploy.py [space-name]

Needs a Hugging Face account + write token (https://huggingface.co/settings/tokens).
Creates the Space if missing, uploads Dockerfile + app, prints the public URL.
The token is never printed.
"""
import os
import subprocess
import sys

SPACE_DEFAULT = "tiago-support-agent"
TITLE = "Support Agent Tools"
EMOJI = "\U0001F916"
DESC = "Multi-agent support with tool-use loop, handoffs and guardrails. Demo UI at /ui."

SPACE_README = f"""---
title: {TITLE}
emoji: {EMOJI}
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# {TITLE}

{ DESC}

- Demo UI: `/ui`
- API docs: `/docs`
- Source: https://github.com/tiagoccepp/support-agent-tools
"""


def main() -> None:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print("Set HF_TOKEN first: HF_TOKEN=hf_xxx python scripts/hf_deploy.py")
        sys.exit(1)
    space = sys.argv[1] if len(sys.argv) > 1 else SPACE_DEFAULT
    try:
        from huggingface_hub import HfApi
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "-q", "install", "huggingface_hub"], check=True)
        from huggingface_hub import HfApi
    api = HfApi(token=token)
    me = api.whoami()["name"]
    repo_id = f"{me}/{space}"
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "README.md"), "w") as f:
            f.write(SPACE_README)
        api.upload_folder(
            repo_id=repo_id, repo_type="space", folder_path=root,
            allow_patterns=["Dockerfile", "requirements.txt", "src/*", "data/*"],
        )
        api.upload_file(
            repo_id=repo_id, repo_type="space",
            path_in_repo="README.md", path_or_fileobj=os.path.join(tmp, "README.md"),
        )
    print(f"Live (building, ~2-5 min): https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    main()
