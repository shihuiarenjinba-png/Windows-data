# Architecture and trust boundary

## Components

- `github_client.py`: GitHub REST search, deterministic candidate scoring, branch tree evidence, exact SHA selection.
- `source_build.py`: isolated checkout, existing script discovery, approval gates, EXE/MSIX invocation.
- `identity.py`: bounded ZIP validation, manifest parsing, Windows package identity and SID APIs.
- `pipeline.py`: orchestration and explicit HOLD transitions.
- `exporter.py`: atomic JSON/CSV output and the Windows Checker handoff contract.
- `gui.py`: bilingual Tkinter UI; build work runs outside the UI thread.
- `gui_validation.py`: deterministic Japanese/English layout checks at a requested resolution.
- `self_package.py`: gated Windows-data packaging, MakeAppx round-trip verification, and identity extraction.

## Trust model

Repository discovery is read-only. A full build executes scripts from the resolved repository, so users must restrict the GitHub owner and review unexpected matches. The tool refuses low-confidence or tied repository/branch matches. Source is checked out at a recorded commit SHA in detached HEAD state.

MSIX creation requires verified identity fields, an approved four-part version, approval evidence for that version and brand assets, and the actual asset files. Missing evidence produces `HOLD`; it is never inferred from filenames or old defaults.

Package metadata is accepted only after reading the generated MSIX. PFN, Publisher ID, Package Full Name, and Package SID are derived through Windows APIs rather than a duplicated hash algorithm.

The Windows Checker handoff deliberately leaves human attestations and provenance confirmation false. This collector does not certify Store readiness, submit packages, publish products, reserve names, or sign packages.

Windows-data's own package uses the same identity, version, Store ID, and asset approval gates as target products. Packaging is attempted only when every official field is verified. The unsigned QA package is unpacked again; its executable hash and embedded source commit must match before it is reported as a candidate. Windows application-control outcomes are observed and recorded without modifying or bypassing policy.
