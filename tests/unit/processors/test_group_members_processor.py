from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gitlabform.processors.group.group_members_processor import GroupMembersProcessor


class TestGroupMembersProcessor:
    def setup_method(self):
        self.processor = GroupMembersProcessor.__new__(GroupMembersProcessor)
        self.processor.gl = MagicMock()

    def test__process_groups_formats_date_expires_at_before_sharing(self):
        group = MagicMock()
        group.shared_with_groups = []
        self.processor.gl.get_group_id.return_value = 123

        self.processor._process_groups(
            group,
            {
                "parent/child": {
                    "group_access": 30,
                    "expires_at": date(2026, 6, 18),
                }
            },
            enforce_group_members=False,
        )

        group.share.assert_called_once_with(123, 30, "2026-06-18")

    def test__process_users_formats_date_expires_at_before_creating_member(self):
        group = MagicMock()
        group.members.list.return_value = []
        self.processor.gl.get_user_id_cached.return_value = 456

        self.processor._process_users(
            {
                "Alice": {
                    "access_level": 30,
                    "expires_at": date(2026, 6, 18),
                }
            },
            enforce_group_members=False,
            keep_bots=False,
            group=group,
        )

        group.members.create.assert_called_once_with(
            {
                "user_id": 456,
                "access_level": 30,
                "expires_at": "2026-06-18",
                "member_role_id": None,
            }
        )


class TestGroupMembersDryRunDiff:
    def setup_method(self):
        self.processor = GroupMembersProcessor.__new__(GroupMembersProcessor)
        self.processor.gl = MagicMock()
        self.processor.configuration_name = "group_members"

    @staticmethod
    def _diff(current: dict, desired: dict) -> str:
        from gitlabform.processors.util.difference_logger import DifferenceLogger

        return DifferenceLogger.log_diff("group_members changes", current, desired, only_changed=True, test=True)

    def _set_gitlab_state(self, members=None, shared_with_groups=None):
        group = self.processor.gl.get_group_by_path_cached.return_value
        group.members.list.return_value = members or []
        group.shared_with_groups = shared_with_groups or []
        return group

    @staticmethod
    def _mock_member(username="RaymondSmith", access_level=30, expires_at=None):
        member = MagicMock(spec=["username", "access_level", "expires_at"])
        member.username = username
        member.access_level = access_level
        member.expires_at = expires_at
        return member

    def test__differing_access_level_shows_in_diff(self):
        self._set_gitlab_state(members=[self._mock_member(access_level=30)])

        text = self._diff(
            self.processor._get_current_state("some/group"),
            self.processor._get_desired_state({"raymondsmith": {"access_level": 40}}),
        )

        assert "user:raymondsmith" in text
        assert "40" in text

    def test__matching_users_and_groups_are_silent(self):
        self._set_gitlab_state(
            members=[self._mock_member(access_level=30, expires_at="2026-12-31")],
            shared_with_groups=[
                {
                    "group_id": 28,
                    "group_name": "Fabio",
                    "group_full_path": "fabio/fabio",
                    "group_access_level": 50,
                    "expires_at": None,
                }
            ],
        )
        config = {
            "RaymondSmith": {"access_level": 30, "expires_at": "2026-12-31"},
            "groups": {"fabio/fabio": {"group_access": 50}},
        }

        assert (
            self._diff(
                self.processor._get_current_state("some/group"),
                self.processor._get_desired_state(config),
            )
            == ""
        )

    def test__desired_state_formats_date_expires_at(self):
        desired = self.processor._get_desired_state(
            {"users": {"alice": {"access_level": 30, "expires_at": date(2026, 6, 18)}}}
        )

        assert desired == {"user:alice": {"access_level": 30, "expires_at": "2026-06-18"}}

    def test__enforce_and_keep_bots_are_not_treated_as_users(self):
        desired = self.processor._get_desired_state({"enforce": True, "keep_bots": True, "bob": {"access_level": 50}})

        assert desired == {"user:bob": {"access_level": 50, "expires_at": None}}

    def test__member_only_in_gitlab_is_named_as_removed_by_enforce(self, caplog):
        self._set_gitlab_state(members=[self._mock_member(username="LeftBehind", access_level=30)])

        with caplog.at_level("INFO"):
            self.processor._print_diff(
                "some/group",
                {"enforce": True, "raymondsmith": {"access_level": 40}},
                diff_only_changed=True,
            )

        assert "user:leftbehind" in caplog.text
        assert "(will be removed by enforce)" in caplog.text

    def test__member_only_in_gitlab_without_enforce_is_named_as_such(self, caplog):
        self._set_gitlab_state(members=[self._mock_member(username="LeftBehind", access_level=30)])

        with caplog.at_level("INFO"):
            self.processor._print_diff(
                "some/group",
                {"raymondsmith": {"access_level": 40}},
                diff_only_changed=True,
            )

        assert "user:leftbehind" in caplog.text
        assert "(only in GitLab)" in caplog.text

    def test__shared_group_only_in_gitlab_is_named_too(self, caplog):
        self._set_gitlab_state(
            shared_with_groups=[
                {
                    "group_id": 28,
                    "group_name": "Fabio",
                    "group_full_path": "fabio/fabio",
                    "group_access_level": 50,
                    "expires_at": None,
                }
            ],
        )

        with caplog.at_level("INFO"):
            self.processor._print_diff("some/group", {"enforce": True}, diff_only_changed=True)

        assert "group:fabio/fabio" in caplog.text
        assert "(will be removed by enforce)" in caplog.text


class TestGroupMembersDiffKeepBots:
    def setup_method(self):
        self.processor = GroupMembersProcessor.__new__(GroupMembersProcessor)
        self.processor.gl = MagicMock()
        self.processor.configuration_name = "group_members"

    @staticmethod
    def _mock_member(username, access_level=30, expires_at=None):
        member = MagicMock(spec=["username", "access_level", "expires_at"])
        member.username = username
        member.access_level = access_level
        member.expires_at = expires_at
        return member

    def _gitlab_has_a_bot_and_a_human(self, shared_with_groups=None):
        group = self.processor.gl.get_group_by_path_cached.return_value
        group.members.list.return_value = [
            self._mock_member("RaymondSmith"),
            self._mock_member("group_1_bot_a1b2c3"),
        ]
        group.shared_with_groups = shared_with_groups or []
        self.processor.gl.get_user_by_username_cached.side_effect = lambda username: SimpleNamespace(
            bot="_bot_" in username
        )

    def _current_side_of_diff(self, config: dict) -> dict:
        with patch("gitlabform.processors.group.group_members_processor.DifferenceLogger") as logger:
            self.processor._print_diff("some/group", config, diff_only_changed=True)
        return logger.log_diff.call_args[0][1]

    def test_an_unconfigured_bot_is_not_shown_leaving_when_keep_bots_is_on(self):
        self._gitlab_has_a_bot_and_a_human()

        current = self._current_side_of_diff(
            {"enforce": True, "keep_bots": True, "users": {"raymondsmith": {"access_level": 40}}}
        )

        assert "user:group_1_bot_a1b2c3" not in current
        assert "user:raymondsmith" in current

    def test_an_unconfigured_bot_is_not_shown_leaving_without_enforce_either(self):
        self._gitlab_has_a_bot_and_a_human()

        current = self._current_side_of_diff({"keep_bots": True, "users": {"raymondsmith": {"access_level": 40}}})

        assert "user:group_1_bot_a1b2c3" not in current

    def test_an_unconfigured_bot_is_still_shown_leaving_when_keep_bots_is_off(self):
        self._gitlab_has_a_bot_and_a_human()

        current = self._current_side_of_diff({"enforce": True, "users": {"raymondsmith": {"access_level": 40}}})

        assert "user:group_1_bot_a1b2c3" in current

    def test_the_enforce_removal_line_is_gone_for_a_kept_bot(self, caplog):
        self._gitlab_has_a_bot_and_a_human()

        with caplog.at_level("INFO"):
            self.processor._print_diff(
                "some/group",
                {"enforce": True, "keep_bots": True, "users": {"raymondsmith": {"access_level": 30}}},
                diff_only_changed=True,
            )

        assert "group_1_bot_a1b2c3" not in caplog.text
        assert "(will be removed by enforce)" not in caplog.text

    def test_a_configured_bot_is_still_diffed_when_keep_bots_is_on(self):
        self._gitlab_has_a_bot_and_a_human()

        current = self._current_side_of_diff(
            {
                "enforce": True,
                "keep_bots": True,
                "users": {"raymondsmith": {"access_level": 40}, "group_1_bot_a1b2c3": {"access_level": 40}},
            }
        )

        assert current["user:group_1_bot_a1b2c3"]["access_level"] == 30

    def test_a_human_member_is_never_spared(self):
        self._gitlab_has_a_bot_and_a_human()

        current = self._current_side_of_diff({"enforce": True, "keep_bots": True, "users": {}})

        assert "user:raymondsmith" in current

    def test_a_shared_group_is_never_spared(self):
        self._gitlab_has_a_bot_and_a_human(
            shared_with_groups=[
                {
                    "group_id": 28,
                    "group_name": "Fabio",
                    "group_full_path": "fabio/fabio",
                    "group_access_level": 50,
                    "expires_at": None,
                }
            ]
        )

        current = self._current_side_of_diff({"enforce": True, "keep_bots": True, "users": {}})

        assert "group:fabio/fabio" in current
