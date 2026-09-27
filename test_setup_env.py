import setup_env


def test_build_env_contents_includes_key_and_model():
    contents = setup_env.build_env_contents("sk-ant-test123", "claude-haiku-4-5-20251001")
    assert "APP_ANTHROPIC_API_KEY=sk-ant-test123" in contents
    assert "APP_ANTHROPIC_MODEL=claude-haiku-4-5-20251001" in contents


def test_write_env_file_writes_key_to_disk(tmp_path):
    env_path = tmp_path / ".env"
    result_path = setup_env.write_env_file("sk-ant-test123", "claude-haiku-4-5-20251001", env_path)
    assert result_path == env_path
    assert env_path.exists()
    assert "sk-ant-test123" in env_path.read_text()


def test_write_env_file_restricts_permissions(tmp_path):
    env_path = tmp_path / ".env"
    setup_env.write_env_file("sk-ant-test123", "claude-haiku-4-5-20251001", env_path)
    mode = env_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_main_never_prints_the_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(setup_env, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "super-secret-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    exit_code = setup_env.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "super-secret-key" not in captured.out
    assert "super-secret-key" not in captured.err
    written = (tmp_path / ".env").read_text()
    assert "super-secret-key" in written
    assert setup_env.DEFAULT_MODEL in written


def test_main_aborts_without_writing_on_empty_key(monkeypatch, capsys, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(setup_env, "ENV_PATH", env_path)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "   ")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    exit_code = setup_env.main()

    assert exit_code == 1
    assert not env_path.exists()
