#!/usr/bin/env python3
import getpass
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ENV_PATH = Path(__file__).parent / ".env"


def build_env_contents(api_key, model):
    return f"APP_ANTHROPIC_API_KEY={api_key}\nAPP_ANTHROPIC_MODEL={model}\n"


def write_env_file(api_key, model, env_path=ENV_PATH):
    env_path.write_text(build_env_contents(api_key, model))
    env_path.chmod(0o600)
    return env_path


def prompt_for_credentials():
    api_key = getpass.getpass("Enter your Meridian Retail app Anthropic API key (input hidden): ")
    model = input(f"Model to use [default: {DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL
    return api_key, model


def main():
    print("Meridian Retail Support Drafting Tool - environment setup")
    api_key, model = prompt_for_credentials()
    if not api_key.strip():
        print("No API key entered. Aborting without writing .env.")
        return 1
    path = write_env_file(api_key.strip(), model, ENV_PATH)
    print(f"Wrote configuration to {path} (key not shown).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
