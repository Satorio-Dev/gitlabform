from unittest.mock import MagicMock, patch

from gitlabform.processors.project.badges_processor import BadgesProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _diff(current: dict, desired: dict) -> str:
    return DifferenceLogger.log_diff("badges changes", current, desired, only_changed=True, test=True)


class TestBadgesProcessorDryRunDiff:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = BadgesProcessor(self.gitlab)

    @staticmethod
    def _gitlab_badge(name="Coverage", image_url="https://shields.io/my/badge"):
        return {
            "id": 1,
            "name": name,
            "link_url": "http://example.com/ci_status.svg?project=example-org/example-project",
            "image_url": image_url,
            "rendered_link_url": "http://example.com/ci_status.svg?project=example-org/example-project",
            "rendered_image_url": "https://shields.io/my/badge",
            "kind": "project",
        }

    def test__differing_image_url_shows_in_diff(self):
        self.gitlab.get_project_badges.return_value = [self._gitlab_badge()]
        config = {
            "coverage": {
                "name": "Coverage",
                "link_url": "http://example.com/ci_status.svg?project=example-org/example-project",
                "image_url": "https://shields.io/my/other-badge",
            }
        }

        text = _diff(
            self.processor._get_current_state("foo/bar"),
            self.processor._get_desired_state(config),
        )

        assert "Coverage" in text
        assert "other-badge" in text

    def test__matching_state_is_silent(self):
        self.gitlab.get_project_badges.return_value = [self._gitlab_badge()]
        config = {
            "coverage": {
                "name": "Coverage",
                "link_url": "http://example.com/ci_status.svg?project=example-org/example-project",
                "image_url": "https://shields.io/my/badge",
            }
        }

        assert (
            _diff(
                self.processor._get_current_state("foo/bar"),
                self.processor._get_desired_state(config),
            )
            == ""
        )

    def test__enforce_flag_is_not_treated_as_a_badge(self):
        desired = self.processor._get_desired_state({"enforce": True})

        assert desired == {}
