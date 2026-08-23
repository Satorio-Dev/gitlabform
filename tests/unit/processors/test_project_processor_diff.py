from typing import cast
from unittest.mock import MagicMock, patch

from gitlab import GitlabGetError

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.project_processor import ProjectProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _make_processor() -> ProjectProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        return ProjectProcessor(MagicMock(GitLab))


def _gl(processor: ProjectProcessor) -> MagicMock:
    return cast(MagicMock, processor.gl)


def _render_diff(processor, project_and_group: str, entity_config: dict) -> str:
    current = processor._get_current_state(project_and_group)
    desired = processor._get_desired_state(entity_config)
    return DifferenceLogger.log_diff("changes", current, desired, only_changed=True, test=True)


class TestProjectDiff:
    def test__diff_reports_difference_in_archive_state(self) -> None:
        processor = _make_processor()
        _gl(processor).get_project_by_path_cached.return_value.archived = False

        diff = _render_diff(processor, "group/project", {"archive": True})

        assert "archive" in diff
        assert "true" in diff

    def test__diff_is_silent_when_archive_state_matches(self) -> None:
        processor = _make_processor()
        _gl(processor).get_project_by_path_cached.return_value.archived = True

        diff = _render_diff(processor, "group/project", {"archive": True})

        assert diff == ""

    def test__transfer_from_is_marked_as_not_available(self) -> None:
        processor = _make_processor()
        _gl(processor).get_project_by_path_cached.return_value.archived = False

        diff = _render_diff(processor, "group/project", {"transfer_from": "old-group/project"})

        assert "old-group/project" in diff
        assert "not available" in diff

    def test__missing_project_yields_empty_current_state(self) -> None:
        processor = _make_processor()
        _gl(processor).get_project_by_path_cached.side_effect = GitlabGetError("404 Project Not Found", 404)

        assert processor._get_current_state("group/project") == {}
