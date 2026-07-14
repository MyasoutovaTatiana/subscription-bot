from app.config import Settings


def test_settings_defaults(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456:ABC-DEF_test_token_value")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.timezone == "Europe/Moscow"
    assert settings.default_reminder_time == "10:00"
    assert settings.scheduler_interval_minutes == 10
    assert "sqlite+aiosqlite" in settings.database_url
