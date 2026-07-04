#!/usr/bin/env python3
from __future__ import annotations

import math
import os
from pathlib import Path


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env", override=True)
    from rdagent.oai.llm_utils import APIBackend

    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY is missing")
    backend = APIBackend()
    embedding = backend.create_embedding("A-share factor health check")
    norm = math.sqrt(sum(value * value for value in embedding))
    if len(embedding) != 512 or not math.isclose(norm, 1.0, rel_tol=1e-6):
        raise SystemExit("local embedding check failed")
    response = backend.build_messages_and_create_chat_completion(
        user_prompt="Reply with OK only.",
        system_prompt="You are a connectivity health check.",
    )
    if not response.strip():
        raise SystemExit("DeepSeek chat check returned an empty response")
    print("health check: local embedding OK; DeepSeek chat OK")


if __name__ == "__main__":
    main()
