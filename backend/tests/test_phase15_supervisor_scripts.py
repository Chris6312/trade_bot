from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def _script_path(name: str) -> Path:
    exact = SCRIPTS_DIR / name
    if exact.exists():
        return exact

    lowered = name.lower()
    for path in SCRIPTS_DIR.iterdir():
        if path.name.lower() == lowered:
            return path

    return exact


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase15_supervisor_scripts_exist() -> None:
    assert _script_path("Start-Bot.ps1").exists()
    assert _script_path("Stop-Bot.ps1").exists()


def test_start_bot_uses_ordered_startup_and_local_alembic() -> None:
    script = _read_text(_script_path("Start-Bot.ps1"))

    postgres_step_index = script.index("Write-Host '1/5 Starting PostgreSQL...'")
    postgres_up_index = script.index("docker compose up -d postgres", postgres_step_index)
    postgres_wait_index = script.index(
        "Wait-ForPostgresReady -ContainerName 'tradingbot_postgres'",
        postgres_step_index,
    )

    alembic_step_index = script.index("Write-Host '2/5 Running Alembic migrations...'")
    alembic_index = script.index("Invoke-LocalAlembic -RepoRoot $repoRoot -PythonExe $pythonExe", alembic_step_index)

    backend_step_index = script.index("Write-Host '3/5 Starting backend...'")
    backend_up_index = script.index("docker compose up -d backend", backend_step_index)
    backend_wait_index = script.index(
        'Wait-ForHttpOk -Url "http://localhost:$backendPort/health" -ExpectedJsonStatus \'ok\'',
        backend_step_index,
    )

    frontend_step_index = script.index("Write-Host '4/5 Starting frontend...'")
    frontend_up_index = script.index("docker compose up -d frontend", frontend_step_index)

    assert postgres_step_index < postgres_up_index < postgres_wait_index < alembic_step_index < alembic_index < backend_step_index < backend_up_index < backend_wait_index < frontend_step_index < frontend_up_index
    assert "pg_isready" in script
    assert "-m alembic -c alembic.ini upgrade head" in script
    assert "bot-state.json" in script
    assert "workerOrder" in script
    assert "Resolve-PythonExe" in script


def test_start_bot_clears_persisted_kill_switch_by_default() -> None:
    script = _read_text(_script_path("Start-Bot.ps1"))

    health_wait_index = script.index(
        'Wait-ForHttpOk -Url "http://localhost:$backendPort/health" -ExpectedJsonStatus \'ok\''
    )
    clear_index = script.index(
        "Clear-KillSwitchIfNeeded -BackendPort $backendPort -ApiPrefix $apiPrefix -KeepKillSwitchEnabled:$KeepKillSwitchEnabled",
        health_wait_index,
    )
    frontend_step_index = script.index("Write-Host '4/5 Starting frontend...'")

    assert "[switch]$KeepKillSwitchEnabled" in script
    assert "/controls/snapshot" in script
    assert "/controls/kill-switch/toggle" in script
    assert "enabled = $false" in script
    assert health_wait_index < clear_index < frontend_step_index


def test_start_bot_opens_operator_log_tabs() -> None:
    script = _read_text(_script_path("Start-Bot.ps1"))

    assert "Trade_Bot - Backend Logs" in script
    assert "Trade_Bot - Worker Stream" in script
    assert "Trade_Bot - Frontend Logs" in script
    assert "Trade_Bot - Postgres Logs" in script
    assert "/system-events?limit=25" in script
    assert "docker compose logs -f backend" in script
    assert "docker compose logs -f frontend" in script
    assert "docker compose logs -f postgres" in script


def test_stop_bot_engages_kill_switch_and_stops_cleanly() -> None:
    script = _read_text(_script_path("Stop-Bot.ps1"))

    kill_switch_index = script.index("/controls/kill-switch/toggle")
    frontend_stop_index = script.index("docker compose stop frontend")
    backend_stop_index = script.index("docker compose stop backend")
    down_index = script.index("docker compose down --remove-orphans")

    assert kill_switch_index < frontend_stop_index < backend_stop_index < down_index
    assert "Start-Sleep -Seconds $DrainSeconds" in script
    assert "Remove-Item $statePath -Force" in script


def test_start_bot_primes_worker_pipeline_before_frontend() -> None:
    script = _read_text(_script_path("Start-Bot.ps1"))

    clear_index = script.index(
        "Clear-KillSwitchIfNeeded -BackendPort $backendPort -ApiPrefix $apiPrefix -KeepKillSwitchEnabled:$KeepKillSwitchEnabled"
    )
    pipeline_index = script.index("Invoke-StartupPipeline -BackendPort $backendPort -ApiPrefix $apiPrefix")
    frontend_step_index = script.index("Write-Host '4/5 Starting frontend...'")

    assert clear_index < pipeline_index < frontend_step_index
    assert "/controls/universe/run-once" in script
    assert "/controls/candles/backfill" in script
    assert "/controls/regime/run-once" in script
    assert "/controls/strategy/run-once" in script
