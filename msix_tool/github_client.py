from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class GitHubError(RuntimeError):
    pass


class AmbiguousRepositoryError(GitHubError):
    pass


class AmbiguousBranchError(GitHubError):
    pass


JsonRequest = Callable[[str], Any]


@dataclass(frozen=True, slots=True)
class Repository:
    full_name: str
    html_url: str
    clone_url: str
    default_branch: str
    description: str
    score: int = 0


@dataclass(frozen=True, slots=True)
class SourceRevision:
    branch: str
    sha: str
    score: int
    evidence: tuple[str, ...]


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def repository_score(app_name: str, repo_name: str, description: str = "") -> int:
    app_norm = _normalized(app_name)
    repo_norm = _normalized(repo_name)
    if not app_norm or not repo_norm:
        return 0
    score = 0
    if app_norm == repo_norm:
        score += 120
    elif app_norm in repo_norm or repo_norm in app_norm:
        score += 80
    app_tokens = _tokens(app_name)
    repo_tokens = _tokens(repo_name)
    shared = app_tokens & repo_tokens
    if app_tokens:
        score += int(50 * len(shared) / len(app_tokens))
    if app_norm in _normalized(description):
        score += 20
    return score


class GitHubClient:
    def __init__(self, token: str | None = None, requester: JsonRequest | None = None):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self._requester = requester

    def _get_json(self, endpoint: str) -> Any:
        if self._requester is not None:
            return self._requester(endpoint)
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "windows-msix-auto-build-identity/0.1",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read(5_000_000).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(2_000).decode("utf-8", "replace")
            except OSError:
                pass
            raise GitHubError(f"GitHub API HTTP {exc.code}: {detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GitHubError(f"GitHub API request failed: {exc}") from exc

    def repository_from_url(self, repo_url: str) -> Repository:
        match = re.fullmatch(
            r"https://github[.]com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:[.]git)?/?",
            repo_url.strip(),
        )
        if not match:
            raise GitHubError("Repository URL must be https://github.com/OWNER/REPO")
        owner, name = match.groups()
        data = self._get_json(f"https://api.github.com/repos/{owner}/{name}")
        return self._repo_from_api(data, 999)

    def find_repository(self, app_name: str, owner: str = "") -> Repository:
        if not app_name.strip():
            raise GitHubError("Application name is required")
        if len(app_name.strip()) > 120:
            raise GitHubError("Application name is too long")
        if owner.strip() and not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner.strip()):
            raise GitHubError("GitHub owner is invalid")
        query = f'"{app_name.strip()}" in:name,description'
        if owner.strip():
            query += f" user:{owner.strip()}"
        endpoint = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": query, "per_page": 25}
        )
        data = self._get_json(endpoint)
        items = data.get("items", []) if isinstance(data, dict) else []
        candidates: list[Repository] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            score = repository_score(
                app_name, str(item.get("name", "")), str(item.get("description") or "")
            )
            candidates.append(self._repo_from_api(item, score))
        candidates.sort(key=lambda value: (-value.score, value.full_name.casefold()))
        if not candidates or candidates[0].score < 80:
            raise GitHubError("No high-confidence GitHub repository match was found")
        if len(candidates) > 1 and candidates[0].score - candidates[1].score < 20:
            names = ", ".join(item.full_name for item in candidates[:3])
            raise AmbiguousRepositoryError(f"Repository match is ambiguous: {names}")
        return candidates[0]

    @staticmethod
    def _repo_from_api(data: dict[str, Any], score: int) -> Repository:
        try:
            return Repository(
                full_name=str(data["full_name"]),
                html_url=str(data["html_url"]),
                clone_url=str(data.get("clone_url") or (str(data["html_url"]) + ".git")),
                default_branch=str(data["default_branch"]),
                description=str(data.get("description") or ""),
                score=score,
            )
        except KeyError as exc:
            raise GitHubError(f"Malformed GitHub repository response: missing {exc}") from exc

    def resolve_revision(self, repo: Repository, branch: str = "") -> SourceRevision:
        owner, name = repo.full_name.split("/", 1)
        branch_data = self._get_json(
            f"https://api.github.com/repos/{owner}/{name}/branches?per_page=100"
        )
        branches = []
        for item in branch_data if isinstance(branch_data, list) else []:
            try:
                branches.append((str(item["name"]), str(item["commit"]["sha"])))
            except (KeyError, TypeError):
                continue
        if branch:
            for name_value, sha in branches:
                if name_value == branch:
                    return SourceRevision(branch, sha, 999, ("explicit branch",))
            raise GitHubError(f"Branch does not exist: {branch}")
        shortlist = sorted(
            branches,
            key=lambda item: (
                0 if item[0] == repo.default_branch else 1,
                0 if re.search(r"(?i)(store|msix|windows|release)", item[0]) else 1,
                item[0].casefold(),
            ),
        )[:20]
        scored: list[SourceRevision] = []
        for name_value, sha in shortlist:
            evidence, score = self._tree_evidence(owner, name, sha)
            if name_value == repo.default_branch:
                score += 5
                evidence.append("default branch")
            if re.search(r"(?i)(store|msix|windows)", name_value):
                score += 8
                evidence.append("branch name indicates Windows packaging")
            scored.append(SourceRevision(name_value, sha, score, tuple(evidence)))
        scored.sort(key=lambda value: (-value.score, value.branch.casefold()))
        if not scored or scored[0].score < 30:
            raise GitHubError("No branch with a detectable Windows build was found")
        if len(scored) > 1 and scored[0].score == scored[1].score:
            raise AmbiguousBranchError(
                f"Branch match is ambiguous: {scored[0].branch}, {scored[1].branch}"
            )
        return scored[0]

    def _tree_evidence(self, owner: str, repo: str, sha: str) -> tuple[list[str], int]:
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}?recursive=1"
        data = self._get_json(endpoint)
        paths = {
            str(item.get("path", "")).replace("\\", "/").casefold()
            for item in data.get("tree", [])
            if isinstance(item, dict) and item.get("type") == "blob"
        }
        evidence: list[str] = []
        score = 0
        exact = {
            "build-windows-portable.ps1": 25,
            "store/build-msix.ps1": 35,
            "store/unsigned_msix_submission_inputs.json": 45,
        }
        for path, points in exact.items():
            if path in paths:
                score += points
                evidence.append(path)
        if any(re.search(r"(^|/)(build[-_].*windows|build[-_]msix)[.]ps1$", p) for p in paths):
            score += 15
            evidence.append("Windows PowerShell build script")
        if any(p.endswith("appxmanifest.xml") for p in paths):
            score += 15
            evidence.append("AppxManifest.xml")
        return evidence, score
