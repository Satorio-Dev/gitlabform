from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.resource_groups_processor import ResourceGroupsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _make_resource_group(key: str, process_mode: str):
    resource_group = MagicMock()
    resource_group.key = key
    resource_group.asdict.return_value = {
        "id": 3,
        "key": key,
        "process_mode": process_mode,
        "created_at": "2021-09-01T08:04:59.650Z",
        "updated_at": "2021-09-01T08:04:59.650Z",
    }
    return resource_group


def _make_processor(process_mode: str = "unordered") -> ResourceGroupsProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = ResourceGroupsProcessor(MagicMock(GitLab))
    processor.gl = MagicMock()
    processor.gl.get_project_by_path_cached.return_value.resource_groups.list.return_value = [
        _make_resource_group("production", process_mode)
    ]
    return processor


class TestResourceGroupsDiff:
    def test_state_differs_diff_says_so(self):
        processor = _make_processor(process_mode="unordered")

        current = processor._get_current_state("foo/bar")
        desired = processor._get_desired_state({"production": {"process_mode": "oldest_first"}})

        text = DifferenceLogger.log_diff("resource_groups changes", current, desired, only_changed=True, test=True)
        assert "production" in text
        assert "oldest_first" in text

    def test_state_matches_diff_is_silent(self):
        processor = _make_processor(process_mode="oldest_first")

        current = processor._get_current_state("foo/bar")
        desired = processor._get_desired_state({"ensure_exists": False, "production": {"process_mode": "oldest_first"}})

        assert "ensure_exists" not in desired
        assert (
            DifferenceLogger.log_diff("resource_groups changes", current, desired, only_changed=True, test=True) == ""
        )


class TestResourceGroupsNotInGitLab:
    @staticmethod
    def _diff(processor, entity_config: dict, caplog) -> str:
        with caplog.at_level("INFO"):
            processor._print_diff("foo/bar", entity_config, diff_only_changed=True)
        return "\n".join(r.message for r in caplog.records if "resource_groups changes" in r.message)

    def test_missing_resource_group_says_the_apply_will_fail(self, caplog):
        processor = _make_processor()

        diff = self._diff(processor, {"staging": {"process_mode": "oldest_first"}}, caplog)

        assert "staging" in diff
        assert "(not in GitLab - apply will fail; see ensure_exists)" in diff
        assert "oldest_first" not in diff

    def test_missing_resource_group_without_ensure_exists_says_it_is_skipped(self, caplog):
        processor = _make_processor()

        diff = self._diff(processor, {"ensure_exists": False, "staging": {"process_mode": "oldest_first"}}, caplog)

        assert "staging" in diff
        assert "(not in GitLab - will be skipped)" in diff

    def test_a_resource_group_gitlab_has_is_diffed_as_before(self, caplog):
        processor = _make_processor(process_mode="unordered")

        diff = self._diff(processor, {"production": {"process_mode": "oldest_first"}}, caplog)

        assert "production" in diff
        assert "oldest_first" in diff
        assert "not in GitLab" not in diff
