from unittest.mock import MagicMock, patch

import pytest
from gitlab import GitlabGetError

from gitlabform.gitlab import GitLab
from gitlabform.processors.group.group_push_rules_processor import GroupPushRulesProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

PUSH_RULES_IN_GITLAB = {
    "id": 2,
    "created_at": "2020-08-17T19:09:19.580Z",
    "commit_committer_check": True,
    "commit_committer_name_check": False,
    "reject_unsigned_commits": False,
    "commit_message_regex": "Fixes \\d+\\..*",
    "commit_message_negative_regex": None,
    "branch_name_regex": None,
    "deny_delete_tag": False,
    "member_check": False,
    "prevent_secrets": False,
    "author_email_regex": None,
    "file_name_regex": None,
    "max_file_size": 100,
}


def _make_processor() -> GroupPushRulesProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = GroupPushRulesProcessor(MagicMock(GitLab))
    processor.gl = MagicMock()
    processor.gl.get_group_by_path_cached.return_value.pushrules.get.return_value.asdict.return_value = dict(
        PUSH_RULES_IN_GITLAB
    )
    return processor


class TestGroupPushRulesDiff:
    def test_state_differs_diff_says_so(self):
        processor = _make_processor()

        current = processor._get_current_state("foo")
        desired = {"commit_message_regex": "JIRA-\\d+:.*", "max_file_size": 100}

        text = DifferenceLogger.log_diff("group_push_rules changes", current, desired, only_changed=True, test=True)
        assert "commit_message_regex" in text
        assert "JIRA" in text
        assert "max_file_size" not in text

    def test_state_matches_diff_is_silent(self):
        processor = _make_processor()

        current = processor._get_current_state("foo")
        desired = {"commit_message_regex": "Fixes \\d+\\..*", "max_file_size": 100}

        assert (
            DifferenceLogger.log_diff("group_push_rules changes", current, desired, only_changed=True, test=True) == ""
        )

    def test_no_push_rules_yet_every_configured_rule_is_a_change(self):
        processor = _make_processor()
        processor.gl.get_group_by_path_cached.return_value.pushrules.get.side_effect = GitlabGetError(response_code=404)

        current = processor._get_current_state("foo")

        assert current == {}
        text = DifferenceLogger.log_diff(
            "group_push_rules changes", current, {"member_check": True}, only_changed=True, test=True
        )
        assert "member_check" in text

    def test_non_404_errors_are_not_swallowed(self):
        processor = _make_processor()
        processor.gl.get_group_by_path_cached.return_value.pushrules.get.side_effect = GitlabGetError(response_code=403)

        with pytest.raises(GitlabGetError):
            processor._get_current_state("foo")
