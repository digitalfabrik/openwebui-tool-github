import os
from typing import Optional, Tuple

import requests
from pydantic import Field
from pydantic.fields import FieldInfo

# The GitHub organisation all repositories are looked up under.
ORG_NAME = "your-org-here"

API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 15
BODY_LIMIT = 4000


def _value(given, fallback):
    """
    Fall back to a sane default when an argument was left unset and still holds
    its pydantic FieldInfo placeholder.
    """

    if isinstance(given, FieldInfo):
        return fallback
    return given


def _truncate(text: str, limit: int = BODY_LIMIT) -> str:
    text = (text or "").strip()
    if not text:
        return "(no description)"
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated, {len(text) - limit} more characters]"


class Tools:
    def __init__(self):
        pass

    def _request(self, path: str, params: Optional[dict] = None) -> Tuple[Optional[object], str]:
        """
        Perform a GET against the GitHub API. Returns (data, error_message).
        """

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = requests.get(
                f"{API_BASE}{path}",
                headers=headers,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            return None, f"Error contacting GitHub: {str(e)}"

        if response.status_code == 404:
            return None, f"Not found: {path} (does it exist under the '{ORG_NAME}' organisation?)"
        if response.status_code in (401, 403):
            if not token:
                return None, (
                    "Access denied. The environment variable 'GITHUB_TOKEN' is not set, "
                    "which is required for private repositories and raises the rate limit."
                )
            return None, "Access denied. The 'GITHUB_TOKEN' is invalid, lacks permission, or is rate limited."
        if not response.ok:
            return None, f"GitHub returned {response.status_code}: {response.text[:200]}"

        try:
            return response.json(), ""
        except ValueError:
            return None, "GitHub returned a response that could not be parsed."

    def list_issues(
        self,
        repository: str = Field(
            ..., description="The name of the repository (without the organisation prefix)."
        ),
        state: str = Field(
            "open", description="Which issues to list: 'open', 'closed' or 'all'."
        ),
        limit: int = Field(20, description="Maximum number of issues to return (1-100)."),
        labels: str = Field(
            "", description="Optional comma-separated list of labels to filter by."
        ),
    ) -> str:
        """
        List the issues of a repository in the organisation.
        """

        state = _value(state, "open")
        labels = _value(labels, "")

        if state not in ("open", "closed", "all"):
            return "Invalid state. Use 'open', 'closed' or 'all'."

        try:
            limit = max(1, min(int(_value(limit, 20)), 100))
        except (TypeError, ValueError):
            limit = 20

        # Pull requests share this endpoint and are discarded below, so over-fetch
        # to avoid returning fewer issues than requested.
        params = {"state": state, "per_page": min(limit * 2, 100)}
        if labels:
            params["labels"] = labels

        data, error = self._request(f"/repos/{ORG_NAME}/{repository}/issues", params)
        if error:
            return error

        # The issues endpoint also returns pull requests; filter them out.
        issues = [item for item in data if "pull_request" not in item][:limit]
        if not issues:
            return f"No {state} issues found in {ORG_NAME}/{repository}."

        lines = [f"Issues in {ORG_NAME}/{repository} (state: {state}):"]
        for issue in issues:
            author = (issue.get("user") or {}).get("login", "unknown")
            label_names = ", ".join(label["name"] for label in issue.get("labels", []))
            line = (
                f"#{issue['number']} [{issue['state']}] {issue['title']}"
                f" — {author}, {issue.get('comments', 0)} comments"
            )
            if label_names:
                line += f", labels: {label_names}"
            lines.append(line)

        return "\n".join(lines)

    def get_issue(
        self,
        repository: str = Field(
            ..., description="The name of the repository (without the organisation prefix)."
        ),
        issue_number: int = Field(..., description="The number of the issue to read."),
    ) -> str:
        """
        Read a single issue of a repository in the organisation, including its description.
        """

        data, error = self._request(f"/repos/{ORG_NAME}/{repository}/issues/{issue_number}")
        if error:
            return error

        author = (data.get("user") or {}).get("login", "unknown")
        label_names = ", ".join(label["name"] for label in data.get("labels", [])) or "none"
        assignees = ", ".join(a["login"] for a in data.get("assignees", [])) or "none"

        return "\n".join(
            [
                f"Issue #{data['number']}: {data['title']}",
                f"Repository: {ORG_NAME}/{repository}",
                f"State: {data['state']}",
                f"Author: {author}",
                f"Created: {data.get('created_at')}",
                f"Updated: {data.get('updated_at')}",
                f"Labels: {label_names}",
                f"Assignees: {assignees}",
                f"Comments: {data.get('comments', 0)}",
                f"URL: {data.get('html_url')}",
                "",
                _truncate(data.get("body")),
            ]
        )

    def get_issue_comments(
        self,
        repository: str = Field(
            ..., description="The name of the repository (without the organisation prefix)."
        ),
        issue_number: int = Field(..., description="The number of the issue to read comments of."),
        limit: int = Field(30, description="Maximum number of comments to return (1-100)."),
    ) -> str:
        """
        Read the comments of an issue of a repository in the organisation.
        """

        try:
            limit = max(1, min(int(_value(limit, 30)), 100))
        except (TypeError, ValueError):
            limit = 30

        data, error = self._request(
            f"/repos/{ORG_NAME}/{repository}/issues/{issue_number}/comments",
            {"per_page": limit},
        )
        if error:
            return error

        if not data:
            return f"Issue #{issue_number} in {ORG_NAME}/{repository} has no comments."

        lines = [f"Comments on issue #{issue_number} in {ORG_NAME}/{repository}:"]
        for comment in data:
            author = (comment.get("user") or {}).get("login", "unknown")
            lines.append("")
            lines.append(f"{author} ({comment.get('created_at')}):")
            lines.append(_truncate(comment.get("body")))

        return "\n".join(lines)
