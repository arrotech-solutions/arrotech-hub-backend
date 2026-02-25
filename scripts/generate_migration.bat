@echo off
if "%~1"=="" (
    echo Usage: .\scripts\generate_migration.bat "Description of changes"
    exit /b 1
)

echo Generating migration script for: %~1
docker-compose run --rm app python -m alembic revision --autogenerate -m "%~1"
echo Done! Migration file created in alembic/versions.