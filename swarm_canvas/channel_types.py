"""Communication observations shared by local and native channels."""

from dataclasses import dataclass


@dataclass
class Line:
    number: int
    agent: str
    text: str
    round: int
    kind: str

    remote_id: str | None = None
    read_by: list[str] | None = None
