#!/usr/bin/env python3
from pathlib import Path

DEFAULT_MODEL = "qwen3:4b"
DEFAULT_HOST = "http://localhost:11434"
ENV_PATH = Path(__file__).parent / ".env"


def build_env_contents(host, model):
    return f"APP_OLLAMA_HOST={host}\nAPP_OLLAMA_MODEL={model}\n"


def write_env_file(host, model, env_path=ENV_PATH):
    env_path.write_text(build_env_contents(host, model))
    env_path.chmod(0o600)
    return env_path


def prompt_for_settings():
    host = input(f"Ollama host [default: {DEFAULT_HOST}]: ").strip() or DEFAULT_HOST
    model = input(f"Model to use [default: {DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL
    return host, model


def main():
    print("Meridian Retail Support Drafting Tool - environment setup")
    host, model = prompt_for_settings()
    path = write_env_file(host, model, ENV_PATH)
    print(f"Wrote configuration to {path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
