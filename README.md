# Windows MSIX Auto Build & Identity Collector

アプリ名からGitHubソースを特定し、そのリポジトリに既に存在するWindowsビルド手順でEXE／MSIXを生成します。生成されたMSIX自体を開き、Identity、Publisher、Publisher ID、PFN、Package SID、Version、Package Full Name、SHA-256を収集します。

The bilingual desktop app resolves an application name to its GitHub source, runs that repository's existing Windows build flow, and reads identity metadata from the generated MSIX itself.

## Quick start / 起動

Python 3.11以降のWindows環境で、追加ランタイム依存なしに起動できます。

```powershell
python run.py
```

GUIでは基本的にアプリ名だけを入力します。既定のGitHub所有者は`shihuiarenjinba-png`で、必要なら変更できます。CLIも利用できます。

```powershell
# アプリ名から検索・ビルド・収集
python run.py build "AI Upload Guard"

# リポジトリとブランチを固定
python run.py build "AI Upload Guard" `
  --repo https://github.com/shihuiarenjinba-png/-AI-Upload-Guard-AI- `
  --branch codex/store-p1-ai-upload-guard-20261023

# 既存MSIXからIdentityのみ収集
python run.py inspect C:\build\Product.msix --output C:\build\identity
```

出力は以下の3ファイルです。

- `msix-identity-report.json`：全結果、成果物SHA-256、HOLD理由
- `msix-identity-report.csv`：同内容のフラットなCSV
- `windows-checker-submission.json`：既存Windows Checkerへ渡す設定。人手確認項目を勝手に`true`にしません

## How it resolves and builds / 解決とビルド

1. GitHub REST APIで名前・説明を検索し、正規化名とトークン一致を採点します。
2. 候補ブランチのGit treeを読み、既存のWindows／MSIXスクリプトとIdentity入力を検出します。
3. 一意に確定したcommit SHAをdetached HEADで取得し、実行直前にも一致を確認します。
4. 対象リポジトリの既存EXEビルドを実行します。
5. Partner Center確認済みIdentity、承認済みVersion、承認済み素材がすべて揃った場合だけ既存MSIXビルドを実行します。
6. MSIXをZIPコンテナとして安全制限付きで開き、`AppxManifest.xml`から値を取得します。
7. PFN／Publisher IDは`PackageFamilyNameFromId`、Package SIDは`DeriveAppContainerSidFromAppContainerName`を使用してWindowsに導出させます。

`GITHUB_TOKEN`はGitHub API読み取り時だけ環境変数から利用できます。トークンを設定、ログ、コマンド引数、成果物へ保存しません。private repositoryのGit clone認証はGit Credential Managerへ委ねます。

## Safety boundary / 安全境界

- 対象リポジトリ、ブランチ、commit、Partner Center由来のIdentity、承認済みVersion、承認済み素材が確定できない場合は`HOLD`します。
- 複数候補が僅差の場合は自動選択しません。
- Partner Centerへの提出、公開、予約名作成、署名の偽装は行いません。
- 既存のWindows CheckerやStore申請ツールの検査・申請機能は重複実装しません。
- 対象リポジトリのビルドスクリプトはコードを実行します。信頼できる所有者／リポジトリだけを指定してください。
- `READY_CANDIDATE_NOT_CERTIFIED`はMicrosoft認定を意味しません。

## Development / 開発

```powershell
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File scripts\build-tool.ps1
```

機能開発は`codex/msix-auto-build-identity-20261025`で行います。`main`へ機能を直接実装・マージしません。

## Microsoft references / 公式参照

- [Package identity overview](https://learn.microsoft.com/windows/apps/desktop/modernize/package-identity-overview)
- [PackageFamilyNameFromId](https://learn.microsoft.com/windows/win32/api/appmodel/nf-appmodel-packagefamilynamefromid)
- [DeriveAppContainerSidFromAppContainerName](https://learn.microsoft.com/windows/win32/api/userenv/nf-userenv-deriveappcontainersidfromappcontainername)
- [ConvertSidToStringSidW](https://learn.microsoft.com/windows/win32/api/sddl/nf-sddl-convertsidtostringsidw)
