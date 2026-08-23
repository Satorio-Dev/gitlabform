from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.group.group_badges_processor import GroupBadgesProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

BADGE_IN_GITLAB = {
    "id": 1,
    "name": "Coverage",
    "link_url": "http://example.com/ci_status.svg?project=%{project_path}&ref=%{default_branch}",
    "image_url": "https://shields.io/my/badge",
    "rendered_link_url": "http://example.com/ci_status.svg?project=example-org/example-project&ref=main",
    "rendered_image_url": "https://shields.io/my/badge",
    "kind": "group",
}


def _make_processor() -> GroupBadgesProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        gitlab = MagicMock(GitLab)
        gitlab.get_group_badges.return_value = [dict(BADGE_IN_GITLAB)]
        return GroupBadgesProcessor(gitlab)


class TestGroupBadgesDiff:
    def test_state_differs_diff_says_so(self):
        processor = _make_processor()

        current = processor._get_current_state("foo")
        desired = processor._get_desired_state(
            {
                "coverage_badge": {
                    "name": "Coverage",
                    "link_url": BADGE_IN_GITLAB["link_url"],
                    "image_url": "https://shields.io/my/other-badge",
                }
            }
        )

        text = DifferenceLogger.log_diff("group_badges changes", current, desired, only_changed=True, test=True)
        assert "Coverage" in text
        assert "other-badge" in text

    def test_state_matches_diff_is_silent(self):
        processor = _make_processor()

        current = processor._get_current_state("foo")
        desired = processor._get_desired_state(
            {
                "coverage_badge": {
                    "name": "Coverage",
                    "link_url": BADGE_IN_GITLAB["link_url"],
                    "image_url": BADGE_IN_GITLAB["image_url"],
                }
            }
        )

        assert DifferenceLogger.log_diff("group_badges changes", current, desired, only_changed=True, test=True) == ""
