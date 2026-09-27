import setup_env


def test_build_env_contents_includes_host_and_model():
    contents = setup_env.build_env_contents("http://localhost:11434", "qwen3:4b")
    assert "APP_OLLAMA_HOST=http://localhost:11434" in contents
    assert "APP_OLLAMA_MODEL=qwen3:4b" in contents


def test_write_env_file_writes_settings_to_disk(tmp_path):
    env_path = tmp_path / ".env"
    result_path = setup_env.write_env_file("http://localhost:11434", "qwen3:4b", env_path)
    assert result_path == env_path
    assert "APP_OLLAMA_MODEL=qwen3:4b" in env_path.read_text()


def test_write_env_file_restricts_permissions(tmp_path):
    env_path = tmp_path / ".env"
    setup_env.write_env_file("http://localhost:11434", "qwen3:4b", env_path)
    mode = env_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_main_uses_defaults_on_empty_input(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_env, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    exit_code = setup_env.main()

    assert exit_code == 0
    written = (tmp_path / ".env").read_text()
    assert setup_env.DEFAULT_MODEL in written
    assert setup_env.DEFAULT_HOST in written
