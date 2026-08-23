from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.members_processor import MembersProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

MEMBER_IN_GITLAB = SimpleNamespace(
    username="jsmith",
    access_level=40,
    expires_at=None,
)

BOT_MEMBER_IN_GITLAB = SimpleNamespace(
    username="project_1_bot_a1b2c3",
    access_level=30,
    expires_at=None,
)

SHARED_GROUP_IN_GITLAB = {
    "group_id": 4,
    "group_name": "Twitter",
    "group_full_path": "twitter",
    "group_access_level": 30,
    "expires_at": None,
}


def _make_processor() -> MembersProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        gitlab = MagicMock(GitLab)
        gitlab.get_groups_from_project.return_value = {"twitter": dict(SHARED_GROUP_IN_GITLAB)}
        processor = MembersProcessor(gitlab)
    processor.gl = MagicMock()
    processor.gl.get_project_by_path_cached.return_value.members.list.return_value = [MEMBER_IN_GITLAB]
    return processor


class TestMembersDiff:
    def test_state_differs_diff_says_so(self):
        processor = _make_processor()

        current = processor._get_current_state("foo/bar")
        desired = processor._get_desired_state(
            {
                "enforce": True,
                "users": {"jsmith": {"access_level": 30}},
                "groups": {"twitter": {"group_access": 30}},
            }
        )

        text = DifferenceLogger.log_diff("members changes", current, desired, only_changed=True, test=True)
        assert "users" in text
        assert "jsmith" in text
        assert "groups" not in text

    def test_state_matches_diff_is_silent(self):
        processor = _make_processor()

        current = processor._get_current_state("foo/bar")
        desired = processor._get_desired_state(
            {
                "enforce": True,
                "keep_bots": True,
                "users": {"JSmith": {"access_level": 40}},
                "groups": {"Twitter": {"group_access": 30}},
            }
        )

        assert DifferenceLogger.log_diff("members changes", current, desired, only_changed=True, test=True) == ""


class TestMembersDiffKeepBots:
    @staticmethod
    def _processor_with_a_bot_member() -> MembersProcessor:
        processor = _make_processor()
        gl = cast(MagicMock, processor.gl)
        gl.get_project_by_path_cached.return_value.members.list.return_value = [
            MEMBER_IN_GITLAB,
            BOT_MEMBER_IN_GITLAB,
        ]
        gl.get_user_by_username_cached.side_effect = lambda username: SimpleNamespace(bot="_bot_" in username)
        return processor

    @staticmethod
    def _current_users_in_diff(processor: MembersProcessor, config: dict) -> dict:
        with patch("gitlabform.processors.project.members_processor.DifferenceLogger") as logger:
            processor._print_diff("foo/bar", config, diff_only_changed=True)
        return logger.log_diff.call_args[0][1]["users"]

    def test_an_unconfigured_bot_is_not_shown_leaving_when_keep_bots_is_on(self):
        processor = self._processor_with_a_bot_member()

        current_users = self._current_users_in_diff(
            processor,
            {"enforce": True, "keep_bots": True, "users": {"jsmith": {"access_level": 40}}},
        )

        assert "project_1_bot_a1b2c3" not in current_users
        assert "jsmith" in current_users

    def test_an_unconfigured_bot_is_still_shown_leaving_when_keep_bots_is_off(self):
        processor = self._processor_with_a_bot_member()

        current_users = self._current_users_in_diff(
            processor,
            {"enforce": True, "users": {"jsmith": {"access_level": 40}}},
        )

        assert "project_1_bot_a1b2c3" in current_users

    def test_a_configured_bot_is_still_diffed_when_keep_bots_is_on(self):
        processor = self._processor_with_a_bot_member()

        current_users = self._current_users_in_diff(
            processor,
            {
                "enforce": True,
                "keep_bots": True,
                "users": {"jsmith": {"access_level": 40}, "project_1_bot_a1b2c3": {"access_level": 40}},
            },
        )

        assert current_users["project_1_bot_a1b2c3"]["access_level"] == 30

    def test_a_human_member_is_never_spared(self):
        processor = self._processor_with_a_bot_member()

        current_users = self._current_users_in_diff(processor, {"enforce": True, "keep_bots": True, "users": {}})

        assert "jsmith" in current_users
