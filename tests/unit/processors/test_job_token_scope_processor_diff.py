from typing import cast
from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.job_token_scope_processor import JobTokenScopeProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _allowlist_entry(entry_id: int) -> MagicMock:
    entry = MagicMock()
    entry.get_id.return_value = entry_id
    return entry


def _make_processor() -> JobTokenScopeProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = JobTokenScopeProcessor(MagicMock(GitLab))

    project = MagicMock()
    project.id = 10

    job_token_scope = project.job_token_scope.get.return_value
    job_token_scope.inbound_enabled = True
    job_token_scope.allowlist.list.return_value = [_allowlist_entry(10), _allowlist_entry(4)]
    job_token_scope.groups_allowlist.list.return_value = [_allowlist_entry(25)]

    allowed_project = MagicMock()
    allowed_project.id = 4
    allowed_group = MagicMock()
    allowed_group.id = 25

    gl = cast(MagicMock, processor.gl)
    gl.get_project_by_path_cached.side_effect = lambda path: {
        "group/project": project,
        "group/allowed-project": allowed_project,
    }[path]
    gl.get_group_by_path_cached.side_effect = lambda path: {"allowed-group": allowed_group}[path]

    return processor


def _render_diff(processor, entity_config: dict) -> str:
    current = processor._get_current_state("group/project")
    desired = processor._get_desired_state(entity_config)
    return DifferenceLogger.log_diff("changes", current, desired, only_changed=True, test=True)


class TestJobTokenScopeDiff:
    def test__diff_reports_difference(self) -> None:
        processor = _make_processor()

        diff = _render_diff(
            processor,
            {
                "limit_access_to_this_project": False,
                "allowlist": {"projects": ["group/allowed-project"], "groups": ["allowed-group"]},
            },
        )

        assert "limit_access_to_this_project" in diff

    def test__diff_is_silent_when_state_matches(self) -> None:
        processor = _make_processor()

        diff = _render_diff(
            processor,
            {
                "limit_access_to_this_project": True,
                "allowlist": {"projects": ["group/allowed-project"], "groups": ["allowed-group"]},
            },
        )

        assert diff == ""

    def test__diff_reports_allowlist_difference(self) -> None:
        processor = _make_processor()

        diff = _render_diff(
            processor,
            {
                "limit_access_to_this_project": True,
                "allowlist": {"groups": ["allowed-group"]},
            },
        )

        assert "allowlist" in diff
        assert "4" in diff
