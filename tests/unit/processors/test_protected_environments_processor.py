from unittest.mock import MagicMock, patch

from gitlabform.processors.shared.protected_environments_processor import ProtectedEnvironmentsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _diff(current: dict, desired: dict) -> str:
    return DifferenceLogger.log_diff("protected_environments changes", current, desired, only_changed=True, test=True)


class TestProtectedEnvironmentsProcessorDryRunDiff:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProtectedEnvironmentsProcessor(self.gitlab)

    @staticmethod
    def _gitlab_environment(access_level=40):
        return {
            "name": "production",
            "deploy_access_levels": [
                {
                    "id": 12,
                    "access_level": access_level,
                    "access_level_description": "Maintainers",
                    "user_id": None,
                    "group_id": None,
                    "group_inheritance_type": 0,
                }
            ],
            "required_approval_count": 0,
        }

    def test__differing_access_level_shows_in_diff(self):
        self.gitlab.list_protected_environments.return_value = [self._gitlab_environment(access_level=40)]
        config = {
            "production": {
                "name": "production",
                "deploy_access_levels": [
                    {"access_level": 30, "access_level_description": "Maintainers", "group_inheritance_type": 0}
                ],
                "required_approval_count": 0,
            }
        }

        text = _diff(
            self.processor._get_current_state("foo/bar"),
            self.processor._get_desired_state(config),
        )

        assert "production" in text
        assert "30" in text

    def test__matching_state_is_silent(self):
        self.gitlab.list_protected_environments.return_value = [self._gitlab_environment()]
        config = {
            "production": {
                "name": "production",
                "deploy_access_levels": [
                    {"access_level": 40, "access_level_description": "Maintainers", "group_inheritance_type": 0}
                ],
                "required_approval_count": 0,
            }
        }

        assert (
            _diff(
                self.processor._get_current_state("foo/bar"),
                self.processor._get_desired_state(config),
            )
            == ""
        )
