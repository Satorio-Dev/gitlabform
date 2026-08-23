from unittest.mock import MagicMock, patch

from gitlabform.processors.group.group_settings_processor import GroupSettingsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _diff(current: dict, desired: dict) -> str:
    return DifferenceLogger.log_diff("group_settings changes", current, desired, only_changed=True, test=True)


class TestGroupSettingsProcessorDryRunDiff:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = GroupSettingsProcessor(self.gitlab)
        self.processor.gl = MagicMock()

    def _set_gitlab_group(self):
        group = self.processor.gl.get_group_by_path_cached.return_value
        group.asdict.return_value = {
            "id": 4,
            "name": "Twitter",
            "path": "twitter",
            "description": "Aliquid qui quis dignissimos distinctio ut commodi voluptas est.",
            "visibility": "public",
            "share_with_group_lock": False,
            "require_two_factor_authentication": False,
            "two_factor_grace_period": 48,
            "project_creation_level": "developer",
            "auto_devops_enabled": None,
            "subgroup_creation_level": "owner",
            "request_access_enabled": False,
            "full_name": "Twitter",
            "full_path": "twitter",
        }
        return group

    def test__differing_setting_shows_in_diff(self):
        self._set_gitlab_group()

        text = _diff(
            self.processor._get_current_state("twitter"),
            {"visibility": "private", "request_access_enabled": False},
        )

        assert "visibility" in text
        assert "private" in text
        assert "request_access_enabled" not in text

    def test__matching_state_is_silent(self):
        self._set_gitlab_group()

        assert (
            _diff(
                self.processor._get_current_state("twitter"),
                {"visibility": "public", "two_factor_grace_period": 48},
            )
            == ""
        )
