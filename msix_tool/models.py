from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Hold:
    code: str
    message_ja: str
    message_en: str
    blocking_stage: str


@dataclass(slots=True)
class PackageIdentity:
    name: str = ""
    publisher: str = ""
    publisher_id: str = ""
    package_family_name: str = ""
    package_sid: str = ""
    version: str = ""
    architecture: str = ""
    resource_id: str = ""
    package_full_name: str = ""
    display_name: str = ""
    publisher_display_name: str = ""
    application_id: str = ""
    executable: str = ""


@dataclass(slots=True)
class Artifact:
    kind: str
    path: str
    sha256: str
    size: int


@dataclass(slots=True)
class RunReport:
    app_name: str
    schema_version: int = 1
    tool_version: str = "0.1.0"
    generated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: str = "HOLD"
    repository: str = ""
    repository_url: str = ""
    source_branch: str = ""
    source_head: str = ""
    store_id: str = ""
    identity: PackageIdentity = field(default_factory=PackageIdentity)
    artifacts: list[Artifact] = field(default_factory=list)
    build_scripts: dict[str, str] = field(default_factory=dict)
    holds: list[Hold] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    windows_checker_config: str = ""
    output_json: str = ""
    output_csv: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_hold(
        self, code: str, message_ja: str, message_en: str, stage: str
    ) -> None:
        if not any(item.code == code for item in self.holds):
            self.holds.append(Hold(code, message_ja, message_en, stage))
        self.status = "HOLD"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
