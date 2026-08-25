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


class TestGroupSettingsWriteOnlySettings:
    """GitLab takes prevent_sharing_groups_outside_hierarchy and
    enabled_git_access_protocol for any group and answers GET with them only for a
    top-level one. Measured on gitlab.com 19.4 on 2026-08-25: 'leadprom' carries both,
    its subgroup 'leadprom/process/gates' carries neither."""

    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = GroupSettingsProcessor(self.gitlab)
        self.processor.gl = MagicMock()

    def _gitlab_group_reports(self, **settings):
        group = self.processor.gl.get_group_by_path_cached.return_value
        group.asdict.return_value = {"id": 4, "path": "gates", "visibility": "private", **settings}
        return group

    def _diff(self, group_path: str, config: dict, caplog) -> str:
        with caplog.at_level("INFO"):
            self.processor._print_diff(group_path, config, diff_only_changed=True)
        return "\n".join(r.message for r in caplog.records if "group_settings changes" in r.message)

    SUBGROUP_CONFIG = {
        "visibility": "private",
        "prevent_sharing_groups_outside_hierarchy": False,
        "enabled_git_access_protocol": "all",
    }

    def test_a_setting_gitlab_does_not_report_is_not_a_difference(self, caplog):
        self._gitlab_group_reports()

        assert self._diff("leadprom/process/gates", self.SUBGROUP_CONFIG, caplog) == ""

    def test_a_setting_gitlab_does_not_report_is_named_in_a_line_of_its_own(self, caplog):
        self._gitlab_group_reports()

        with caplog.at_level("INFO"):
            self.processor._print_diff("leadprom/process/gates", self.SUBGROUP_CONFIG, True)

        said = [r.message for r in caplog.records if "does not report" in r.message]
        assert len(said) == 1
        assert "enabled_git_access_protocol" in said[0]
        assert "prevent_sharing_groups_outside_hierarchy" in said[0]

    def test_the_same_setting_is_diffed_where_gitlab_does_report_it(self, caplog):
        self._gitlab_group_reports(
            prevent_sharing_groups_outside_hierarchy=True,
            enabled_git_access_protocol="ssh",
        )

        text = self._diff("leadprom", self.SUBGROUP_CONFIG, caplog)

        assert "prevent_sharing_groups_outside_hierarchy" in text
        assert "enabled_git_access_protocol" in text
        assert '"ssh" => "all"' in text

    def test_a_setting_gitlab_reports_and_the_config_matches_stays_silent(self, caplog):
        self._gitlab_group_reports(
            prevent_sharing_groups_outside_hierarchy=False,
            enabled_git_access_protocol="all",
        )

        assert self._diff("leadprom", self.SUBGROUP_CONFIG, caplog) == ""

    def test_an_ordinary_unreported_setting_is_still_a_difference(self, caplog):
        self._gitlab_group_reports()

        text = self._diff("leadprom/process/gates", {"two_factor_grace_period": 48}, caplog)

        assert "two_factor_grace_period" in text

    def test_the_apply_path_still_sends_a_setting_gitlab_does_not_report(self):
        group = self._gitlab_group_reports()

        self.processor._process_configuration(
            "leadprom/process/gates",
            {"group_settings": dict(self.SUBGROUP_CONFIG)},
        )

        assert group.save.called
        assert group.enabled_git_access_protocol == "all"
