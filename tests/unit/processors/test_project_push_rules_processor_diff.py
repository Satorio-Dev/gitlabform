from unittest.mock import MagicMock, patch

from gitlab import GitlabGetError
from gitlab.exceptions import GitlabParsingError

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.project_push_rules_processor import ProjectPushRulesProcessor

PUSH_RULES_IN_GITLAB = {
    "id": 2,
    "project_id": 3,
    "created_at": "2020-08-17T19:09:19.580Z",
    "commit_committer_check": True,
    "commit_committer_name_check": False,
    "reject_unsigned_commits": False,
    "commit_message_regex": "Fixes \\d+\\..*",
    "commit_message_negative_regex": None,
    "branch_name_regex": None,
    "deny_delete_tag": False,
    "member_check": False,
    "prevent_secrets": True,
    "author_email_regex": None,
    "file_name_regex": None,
    "max_file_size": 100,
}


def _make_processor() -> ProjectPushRulesProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = ProjectPushRulesProcessor(MagicMock(GitLab))
    processor.gl = MagicMock()
    processor.gl.get_project_by_path_cached.return_value.pushrules.get.return_value.asdict.return_value = dict(
        PUSH_RULES_IN_GITLAB
    )
    return processor


def _diff(processor: ProjectPushRulesProcessor, config: dict, caplog) -> str:
    with caplog.at_level("INFO"):
        processor._print_diff("group/project", config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if "project_push_rules changes" in r.message)


class TestProjectPushRulesDiff:
    def test_state_differs_diff_says_so(self, caplog):
        text = _diff(_make_processor(), {"commit_message_regex": "JIRA-\\d+:.*", "max_file_size": 100}, caplog)

        assert "commit_message_regex" in text
        assert "JIRA" in text
        assert "max_file_size" not in text

    def test_turning_a_guard_off_is_reported(self, caplog):
        text = _diff(_make_processor(), {"prevent_secrets": False}, caplog)

        assert "prevent_secrets" in text
        assert "true" in text and "false" in text

    def test_state_matches_diff_is_silent(self, caplog):
        assert _diff(_make_processor(), {"commit_message_regex": "Fixes \\d+\\..*", "max_file_size": 100}, caplog) == ""

    def test_no_push_rules_yet_means_every_configured_rule_is_a_change(self, caplog):
        processor = _make_processor()
        processor.gl.get_project_by_path_cached.return_value.pushrules.get.side_effect = GitlabGetError(
            "404 Not found", 404
        )

        text = _diff(processor, {"prevent_secrets": True}, caplog)

        assert "prevent_secrets" in text

    def test_unparseable_null_answer_is_read_as_not_configured_yet(self, caplog):
        processor = _make_processor()
        processor.gl.get_project_by_path_cached.return_value.pushrules.get.side_effect = GitlabParsingError(
            "Failed to parse the server message"
        )

        text = _diff(processor, {"prevent_secrets": True}, caplog)

        assert "prevent_secrets" in text

    def test_other_get_errors_are_not_swallowed(self, caplog):
        processor = _make_processor()
        processor.gl.get_project_by_path_cached.return_value.pushrules.get.side_effect = GitlabGetError(
            "403 Forbidden", 403
        )

        try:
            _diff(processor, {"prevent_secrets": True}, caplog)
        except GitlabGetError as raised:
            assert raised.response_code == 403
        else:
            raise AssertionError("a 403 must not be reported as 'no push rules yet'")
