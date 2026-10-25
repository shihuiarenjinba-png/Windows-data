# Windows MSIX Auto Build & Identity Collector

Windowsアプリ名からGitHubソースを特定し、既存のWindowsビルド手順を利用してEXE／MSIXを生成し、パッケージのIdentity情報とSHA-256を収集するためのツールです。

This project resolves an application name to its GitHub source, uses the repository's existing Windows build flow to produce EXE/MSIX artifacts, and extracts package identity metadata and SHA-256 digests.

## Safety boundary / 安全境界

- 対象リポジトリ、ブランチ、commit、Partner Center由来のIdentity、承認済みVersion、承認済み素材が確定できない場合は`HOLD`します。
- Partner Centerへの提出、公開、予約名作成、署名の偽装は行いません。
- 既存のWindows CheckerやStore申請ツールの機能は重複実装せず、検査用の引き渡しデータを生成します。
- The tool stops with `HOLD` when required source, identity, version, or approved asset evidence is missing or ambiguous.

Development is performed on `codex/msix-auto-build-identity-20261025`; feature work is not committed directly to `main`.
