from typing import cast
from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.integrations_processor import IntegrationsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

SLACK_WEBHOOK = "https://hooks.slack.example/services/T00000000/B00000000/PLACEHOLDER"

SLACK_INTEGRATION_IN_GITLAB = {
    "id": 9,
    "title": "Slack notifications",
    "slug": "slack",
    "created_at": "2023-01-24T14:44:56.990Z",
    "updated_at": "2023-01-27T13:24:24.089Z",
    "active": True,
    "commit_events": True,
    "push_events": True,
    "issues_events": True,
    "merge_requests_events": True,
    "properties": {
        "webhook": SLACK_WEBHOOK,
        "username": "gitlab",
        "notify_only_broken_pipelines": True,
    },
}


def _make_processor(integration_in_gitlab: dict) -> IntegrationsProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = IntegrationsProcessor(MagicMock(GitLab))

    project = cast(MagicMock, processor.gl).get_project_by_path_cached.return_value

    active_integration = MagicMock()
    active_integration.active = integration_in_gitlab["active"]
    active_integration.slug = integration_in_gitlab["slug"]
    inactive_integration = MagicMock()
    inactive_integration.active = False
    inactive_integration.slug = "jira"

    project.integrations.list.return_value = [active_integration, inactive_integration]
    project.integrations.get.return_value.asdict.return_value = integration_in_gitlab

    return processor


def _render_diff(processor, entity_config: dict) -> str:
    current = processor._get_current_state("group/project")
    desired = processor._get_desired_state(entity_config)
    return DifferenceLogger.log_diff("changes", current, desired, only_changed=True, test=True)


class TestIntegrationsDiff:
    def test__diff_reports_difference(self) -> None:
        processor = _make_processor(SLACK_INTEGRATION_IN_GITLAB)

        diff = _render_diff(
            processor,
            {
                "slack": {
                    "webhook": SLACK_WEBHOOK,
                    "username": "gitlab",
                    "notify_only_broken_pipelines": False,
                }
            },
        )

        assert "slack" in diff
        assert "notify_only_broken_pipelines" in diff

    def test__diff_is_silent_when_state_matches(self) -> None:
        processor = _make_processor(SLACK_INTEGRATION_IN_GITLAB)

        diff = _render_diff(
            processor,
            {
                "slack": {
                    "webhook": SLACK_WEBHOOK,
                    "username": "gitlab",
                    "notify_only_broken_pipelines": True,
                }
            },
        )

        assert diff == ""

    def test__secrets_do_not_leak_into_the_diff(self) -> None:
        processor = _make_processor(SLACK_INTEGRATION_IN_GITLAB)

        diff = _render_diff(
            processor,
            {
                "slack": {
                    "webhook": "https://hooks.slack.com/services/T000/B000/other",
                    "username": "gitlab",
                    "notify_only_broken_pipelines": True,
                }
            },
        )

        assert "slack" in diff
        assert SLACK_WEBHOOK not in diff
        assert "https://hooks.slack.com/services/T000/B000/other" not in diff
        assert "<secret " in diff

    def test__inactive_integrations_are_not_part_of_current_state(self) -> None:
        processor = _make_processor(SLACK_INTEGRATION_IN_GITLAB)

        current = processor._get_current_state("group/project")

        assert set(current.keys()) == {"slack"}


def _print_diff(processor, entity_config: dict, caplog) -> str:
    """Goes through _print_diff(), unlike _render_diff() above: what the config marks
    for deletion is reconciled against GitLab there, with both sides in hand."""
    with caplog.at_level("INFO"):
        processor._print_diff("group/project", entity_config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if "integrations changes" in r.message)


class TestIntegrationsDeleteFlag:
    def test_an_integration_marked_for_deletion_reads_as_a_deletion(self, caplog) -> None:
        processor = _make_processor(SLACK_INTEGRATION_IN_GITLAB)

        diff = _print_diff(processor, {"slack": {"delete": True}}, caplog)

        assert "slack" in diff
        assert "(will be deleted)" in diff

    def test_an_integration_gitlab_has_not_got_is_not_promised_a_deletion(self, caplog) -> None:
        processor = _make_processor(SLACK_INTEGRATION_IN_GITLAB)

        diff = _print_diff(processor, {"jira": {"delete": True}}, caplog)

        assert "jira" in diff
        assert "(not in GitLab - nothing to delete)" in diff
        assert "(will be deleted)" not in diff
