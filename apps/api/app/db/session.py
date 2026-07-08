from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base


class Database:
    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        if url.drivername.startswith("sqlite") and url.database not in {None, "", ":memory:"}:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(database_url, connect_args=connect_args)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        Base.metadata.create_all(self.engine)
        self._apply_sqlite_compat_migrations()

    def _apply_sqlite_compat_migrations(self) -> None:
        if not self.engine.url.drivername.startswith("sqlite"):
            return
        inspector = inspect(self.engine)
        if "command_records" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("command_records")}
        with self.engine.begin() as connection:
            if "run_id" not in columns:
                connection.execute(text("ALTER TABLE command_records ADD COLUMN run_id VARCHAR(36)"))
            if "command_origin" not in columns:
                connection.execute(
                    text("ALTER TABLE command_records ADD COLUMN command_origin VARCHAR(40) DEFAULT 'external_binary'")
                )
            connection.execute(
                text(
                    """
                    UPDATE command_records
                    SET command_origin = 'runtime_internal'
                    WHERE command_origin = 'external_binary'
                      AND run_id IN (SELECT id FROM runs WHERE source = 'opencode')
                      AND (
                        lower(command_line) LIKE '%\\.local\\share\\opencode\\snapshot%'
                        OR lower(command_line) LIKE 'git rev-parse%'
                        OR lower(command_line) LIKE 'git remote get-url%'
                        OR lower(command_line) LIKE 'git rev-list%'
                        OR lower(command_line) LIKE 'git --no-optional-locks%'
                      )
                    """
                )
            )
            opencode_tool_commands = connection.execute(
                text(
                    """
                    SELECT run_id, payload
                    FROM events
                    WHERE run_id IN (SELECT id FROM runs WHERE source = 'opencode')
                      AND event_type = 'COMMAND_OUTPUT'
                    """
                )
            ).fetchall()
            opencode_commands = connection.execute(
                text(
                    """
                    SELECT id, run_id, command_line
                    FROM command_records
                    WHERE command_origin = 'external_binary'
                      AND run_id IN (SELECT id FROM runs WHERE source = 'opencode')
                    """
                )
            ).fetchall()
            for row in opencode_tool_commands:
                command = _tool_command_from_payload(row[1])
                if command is None:
                    continue
                candidates = {_normalize_for_agent_match(candidate) for candidate in _agent_tool_command_candidates(command)}
                command_ids = [
                    command_row[0]
                    for command_row in opencode_commands
                    if command_row[1] == row[0]
                    and _normalize_for_agent_match(command_row[2]) in candidates
                ]
                for candidate in _agent_tool_command_candidates(command):
                    connection.execute(
                        text(
                            """
                            UPDATE command_records
                            SET command_origin = 'agent_tool'
                            WHERE command_origin = 'external_binary'
                              AND run_id IN (SELECT id FROM runs WHERE source = 'opencode')
                              AND command_line = :command_line
                            """
                        ),
                        {"command_line": candidate},
                    )
                for command_id in command_ids:
                    connection.execute(
                        text(
                            """
                            UPDATE command_records
                            SET command_origin = 'agent_tool'
                            WHERE id = :command_id
                            """
                        ),
                        {"command_id": command_id},
                    )
            connection.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'COMPLETED'
                    WHERE source = 'opencode'
                      AND status = 'FAILED'
                      AND EXISTS (
                        SELECT 1 FROM events e
                        WHERE e.run_id = runs.id
                          AND e.event_type = 'COMMAND_OUTPUT'
                          AND (
                            json_extract(e.payload, '$.raw_event.type') = 'text'
                            OR json_extract(e.payload, '$.raw_event.part.reason') = 'stop'
                          )
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM command_records c
                        WHERE c.run_id = runs.id
                          AND (
                            c.status IN ('REJECTED', 'TIMEOUT')
                            OR (c.requires_approval = 1 AND c.status IN ('FAILED', 'REJECTED', 'TIMEOUT'))
                          )
                      )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE events
                    SET event_type = 'RUN_COMPLETED',
                        message = 'Run completed.',
                        payload = '{"status":"completed"}'
                    WHERE event_type = 'RUN_FAILED'
                      AND run_id IN (
                        SELECT id FROM runs
                        WHERE source = 'opencode' AND status = 'COMPLETED'
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM command_records c
                        WHERE c.run_id = events.run_id
                          AND (
                            c.status IN ('REJECTED', 'TIMEOUT')
                            OR (c.requires_approval = 1 AND c.status IN ('FAILED', 'REJECTED', 'TIMEOUT'))
                          )
                      )
                    """
                )
            )

    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session


def _tool_command_from_payload(payload: Any) -> str | None:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    raw_event = payload.get("raw_event")
    if not isinstance(raw_event, dict) or raw_event.get("type") != "tool_use":
        return None
    part = raw_event.get("part")
    if not isinstance(part, dict):
        return None
    state = part.get("state")
    if not isinstance(state, dict):
        return None
    input_payload = state.get("input")
    if not isinstance(input_payload, dict):
        return None
    command = input_payload.get("command")
    return command if isinstance(command, str) and command else None


def _agent_tool_command_candidates(command_line: str) -> list[str]:
    candidates: list[str] = []
    for candidate in [command_line, *re.split(r"\s*(?:;|&&|\|\|)\s*", command_line)]:
        normalized = candidate.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _normalize_for_agent_match(command_line: str) -> str:
    return " ".join(command_line.replace('"', "'").split())
