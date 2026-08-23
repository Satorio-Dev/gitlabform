from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.members_processor import MembersProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

MEMBER_IN_GITLAB = SimpleNamespace(
    username="jsmith",
    access_level=40,
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
