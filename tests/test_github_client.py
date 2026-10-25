from __future__ import annotations

import unittest

from msix_tool.github_client import GitHubClient, GitHubError, repository_score


class GitHubClientTests(unittest.TestCase):
    def test_repository_score_prefers_normalized_exact_name(self) -> None:
        exact = repository_score("AI Upload Guard", "-AI-Upload-Guard-AI-")
        unrelated = repository_score("AI Upload Guard", "Windows-data")
        self.assertGreaterEqual(exact, 80)
        self.assertGreater(exact, unrelated)

    def test_resolves_repository_and_packaging_branch(self) -> None:
        def request(endpoint: str):
            if "/search/repositories" in endpoint:
                return {
                    "items": [
                        {
                            "name": "-AI-Upload-Guard-AI-",
                            "full_name": "shihuiarenjinba-png/-AI-Upload-Guard-AI-",
                            "html_url": "https://github.com/shihuiarenjinba-png/-AI-Upload-Guard-AI-",
                            "clone_url": "https://github.com/shihuiarenjinba-png/-AI-Upload-Guard-AI-.git",
                            "default_branch": "main",
                            "description": "AI Upload Guard",
                        }
                    ]
                }
            if endpoint.endswith("/branches?per_page=100"):
                return [
                    {"name": "main", "commit": {"sha": "1" * 40}},
                    {
                        "name": "codex/store-p1-ai-upload-guard-20261023",
                        "commit": {"sha": "5e9b3b7805193fdefc903c6310245f9586732ae4"},
                    },
                ]
            if ("/git/trees/" + "1" * 40) in endpoint:
                return {"tree": [{"type": "blob", "path": "README.md"}]}
            if "/git/trees/5e9b3b7805193fdefc903c6310245f9586732ae4" in endpoint:
                return {
                    "tree": [
                        {"type": "blob", "path": "build-windows-portable.ps1"},
                        {"type": "blob", "path": "store/build-msix.ps1"},
                        {
                            "type": "blob",
                            "path": "store/unsigned_msix_submission_inputs.json",
                        },
                    ]
                }
            self.fail(f"Unexpected endpoint: {endpoint}")

        client = GitHubClient(requester=request)
        repository = client.find_repository("AI Upload Guard", "shihuiarenjinba-png")
        revision = client.resolve_revision(repository)
        self.assertEqual(repository.full_name, "shihuiarenjinba-png/-AI-Upload-Guard-AI-")
        self.assertEqual(revision.branch, "codex/store-p1-ai-upload-guard-20261023")
        self.assertEqual(revision.sha, "5e9b3b7805193fdefc903c6310245f9586732ae4")

    def test_rejects_search_owner_injection(self) -> None:
        client = GitHubClient(requester=lambda _endpoint: self.fail("request should not run"))
        with self.assertRaises(GitHubError):
            client.find_repository("Example", "owner user:someone-else")


if __name__ == "__main__":
    unittest.main()
