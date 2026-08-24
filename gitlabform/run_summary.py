import json
import sys
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import requests

MACHINE_SUMMARY_PREFIX = "GITLABFORM_SUMMARY:"


class RunSummary:
    """What the run did, on one line that a program can read.

    The human summary is written through rich, which wraps every line to the width of
    the terminal. A project whose path is longer than that width is torn across two
    lines, and a reader that counts lines or matches a path on one counts wrong - on
    one measured run of 58 nodes an outside counter found 51. This line is written
    straight to stdout and never through rich, so it stays one line whatever the
    terminal is, and it carries the counts as values rather than as prose.

    A section counts as changed for a node when a request that is not a GET was
    accepted by GitLab while that node's section was being applied. Both of the API
    clients gitlabform uses share the one requests session, so watching that session
    sees every REST call either of them makes. What it does not see: GraphQL, which
    goes through its own client - it is only read from today, and a mutation added
    there would be missing from this line.
    """

    def __init__(self) -> None:
        self.changes: dict[str, list[str]] = {}
        self._applying: Optional[tuple[str, str]] = None

    def forget(self) -> None:
        self.changes = {}
        self._applying = None

    @contextmanager
    def applying(self, node: str, section: str) -> Iterator[None]:
        previous = self._applying
        self._applying = (node, section)
        try:
            yield
        finally:
            self._applying = previous

    def record_write(self) -> None:
        if self._applying is None:
            return

        node, section = self._applying
        sections = self.changes.setdefault(node, [])
        if section not in sections:
            sections.append(section)

    def watch(self, session: requests.Session) -> None:
        def note(response: requests.Response, *args: Any, **kwargs: Any) -> None:
            if response.request.method != "GET" and response.ok:
                self.record_write()

        session.hooks["response"].append(note)

    def line(self, groups_ok: int, projects_ok: int, failed: list[str]) -> str:
        summary = {
            "groups_ok": groups_ok,
            "projects_ok": projects_ok,
            "failed": failed,
            "changes": dict(sorted(self.changes.items())),
        }
        return f"{MACHINE_SUMMARY_PREFIX} {json.dumps(summary, ensure_ascii=False)}"

    def show(self, groups_ok: int, projects_ok: int, failed: list[str]) -> None:
        print(self.line(groups_ok, projects_ok, failed), file=sys.stdout, flush=True)


run_summary = RunSummary()
