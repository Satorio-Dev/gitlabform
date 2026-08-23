from typing import cast
from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.group.group_hooks_processor import GroupHooksProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

HOOK_IN_GITLAB = {
    "id": 1,
    "url": "http://example.com/hook",
    "group_id": 3,
    "push_events": True,
    "push_events_branch_filter": "",
    "issues_events": True,
    "merge_requests_events": True,
    "enable_ssl_verification": True,
    "alert_status": "executable",
    "created_at": "2012-10-12T17:04:47Z",
    "url_variables": [],
}

HOOK_CONFIG = {
    key: value for key, value in HOOK_IN_GITLAB.items() if key not in ("id", "group_id", "created_at", "url")
}


def _make_processor(hooks_in_gitlab: list, enterprise: bool = True) -> GroupHooksProcessor:
    gitlab_mock = MagicMock()
    gitlab_mock.enterprise = enterprise
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = GroupHooksProcessor(gitlab_mock)

    hooks = []
    for hook_in_gitlab in hooks_in_gitlab:
        hook = MagicMock()
        hook.asdict.return_value = hook_in_gitlab
        hooks.append(hook)

    cast(MagicMock, processor.gl).get_group_by_path_cached.return_value.hooks.list.return_value = hooks

    return processor


def _render_diff(processor, entity_config: dict) -> str:
    current = processor._get_current_state("some_group")
    desired = processor._get_desired_state(entity_config)
    return DifferenceLogger.log_diff("changes", current, desired, only_changed=True, test=True)


class TestGroupHooksDiff:
    def test__diff_reports_difference(self) -> None:
        processor = _make_processor([HOOK_IN_GITLAB])

        diff = _render_diff(
            processor,
            {"enforce": True, "http://example.com/hook": {**HOOK_CONFIG, "push_events": False}},
        )

        assert "http://example.com/hook" in diff
        assert "push_events" in diff

    def test__diff_is_silent_when_state_matches(self) -> None:
        processor = _make_processor([HOOK_IN_GITLAB])

        diff = _render_diff(processor, {"enforce": True, "http://example.com/hook": HOOK_CONFIG})

        assert diff == ""

    def test__token_is_reported_but_masked(self) -> None:
        processor = _make_processor([HOOK_IN_GITLAB])

        diff = _render_diff(
            processor,
            {"http://example.com/hook": {**HOOK_CONFIG, "token": "very-secret-token"}},
        )

        assert diff != ""
        assert "very-secret-token" not in diff
        assert "<secret " in diff

    def test__no_diff_support_on_community_edition(self) -> None:
        processor = _make_processor([], enterprise=False)

        assert processor._get_current_state("some_group") is None


class TestGroupHooksDiffThroughPrintDiff:
    @staticmethod
    def _diff(processor, entity_config: dict, caplog) -> str:
        with caplog.at_level("INFO"):
            processor._print_diff("some_group", entity_config, diff_only_changed=True)
        return "\n".join(r.message for r in caplog.records if "group_hooks changes" in r.message)

    def test__key_the_config_does_not_declare_is_not_a_difference(self, caplog) -> None:
        processor = _make_processor([HOOK_IN_GITLAB])

        assert self._diff(processor, {"http://example.com/hook": {"push_events": True}}, caplog) == ""

    def test__hook_only_in_gitlab_is_reported_as_removed_by_enforce(self, caplog) -> None:
        processor = _make_processor([HOOK_IN_GITLAB])

        diff = self._diff(processor, {"enforce": True, "http://other.example.com/hook": HOOK_CONFIG}, caplog)

        assert "http://example.com/hook" in diff
        assert "(will be removed by enforce)" in diff

    def test__hook_marked_for_deletion_reads_as_a_deletion(self, caplog) -> None:
        processor = _make_processor([HOOK_IN_GITLAB])

        diff = self._diff(processor, {"http://example.com/hook": {"delete": True}}, caplog)

        assert "(will be deleted)" in diff

    def test__hook_marked_for_deletion_that_does_not_exist_is_named_but_not_promised(self, caplog) -> None:
        processor = _make_processor([])

        diff = self._diff(processor, {"http://example.com/hook": {"delete": True}}, caplog)

        assert "http://example.com/hook" in diff
        assert "(not in GitLab - nothing to delete)" in diff
        assert "(will be deleted)" not in diff
