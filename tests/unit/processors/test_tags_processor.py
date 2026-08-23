from unittest.mock import MagicMock, patch

from gitlabform.processors.project.tags_processor import TagsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _protected_tag(name="release-*", access_level=40, user_id=None, group_id=None):
    """A realistic body of GET /projects/:id/protected_tags."""
    tag = MagicMock()
    tag.asdict.return_value = {
        "name": name,
        "create_access_levels": [
            {
                "id": 1,
                "access_level": access_level,
                "access_level_description": "Maintainers",
                "user_id": user_id,
                "group_id": group_id,
                "deploy_key_id": None,
            }
        ],
    }
    return tag


class TestTagsDiff:
    def setup_method(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = TagsProcessor(MagicMock(), strict=False)
        self.project = MagicMock()
        self.processor.gl.get_project_by_path_cached.return_value = self.project

    def _diff(self, protected_tags, configured_tags):
        self.project.protectedtags.list.return_value = protected_tags
        return DifferenceLogger.log_diff(
            "tags changes",
            self.processor._get_current_state("group/project"),
            self.processor._get_desired_state(configured_tags),
            only_changed=True,
            test=True,
        )

    def test_no_diff_when_state_matches(self):
        config = {"release-*": {"protected": True, "allowed_to_create": [{"access_level": 40}]}}
        assert self._diff([_protected_tag()], config) == ""

    def test_diff_names_the_tag_when_access_level_differs(self):
        config = {"release-*": {"protected": True, "allowed_to_create": [{"access_level": 30}]}}
        diff = self._diff([_protected_tag(access_level=40)], config)
        assert "release-*" in diff
        assert "30" in diff
        assert "40" in diff

    def test_diff_shows_tag_to_be_unprotected(self):
        diff = self._diff([_protected_tag()], {"release-*": {"protected": False}})
        assert "release-*" in diff
        assert '"protected": false' in diff

    def test_no_diff_when_configured_user_resolves_to_current_user_id(self):
        self.processor.gl.get_user_id_cached.return_value = 42
        config = {"release-*": {"protected": True, "allowed_to_create": [{"user": "bob"}]}}
        assert self._diff([_protected_tag(access_level=None, user_id=42)], config) == ""

    def test_unresolvable_user_stays_visible_in_diff(self):
        self.processor.gl.get_user_id_cached.return_value = None
        config = {"release-*": {"protected": True, "allowed_to_create": [{"user": "ghost"}]}}
        diff = self._diff([_protected_tag(access_level=None, user_id=42)], config)
        assert "ghost" in diff

    def test_desired_state_folds_create_access_level_shortcut(self):
        desired = self.processor._get_desired_state({"v*": {"protected": True, "create_access_level": 40}})
        assert desired == {"v*": {"protected": True, "allowed_to_create": [{"access_level": 40}]}}

    def test_no_diff_for_a_star_tag_whose_state_matches(self):
        self.processor.gl.get_user_id_cached.return_value = 10843916
        config = {"*": {"protected": True, "allowed_to_create": [{"user": "vitallica"}]}}
        tag_in_gitlab = _protected_tag(name="*", access_level=40, user_id=10843916)

        assert self._diff([tag_in_gitlab], config) == ""

    def test_access_level_reported_alongside_a_user_is_not_diffed(self):
        current = self.processor._normalize_access_levels(
            [{"id": 1, "access_level": 40, "access_level_description": "A User", "user_id": 42, "group_id": None}]
        )

        assert current == [{"user_id": 42}]

    def test_access_level_reported_alongside_a_group_is_not_diffed(self):
        current = self.processor._normalize_access_levels(
            [{"id": 2, "access_level": 30, "access_level_description": "A Group", "user_id": None, "group_id": 7}]
        )

        assert current == [{"group_id": 7}]

    def test_a_role_based_access_level_is_still_diffed(self):
        current = self.processor._normalize_access_levels(
            [{"id": 3, "access_level": 40, "access_level_description": "Maintainers", "user_id": None}]
        )

        assert current == [{"access_level": 40}]

    def test_changed_access_level_on_a_star_tag_is_still_loud(self):
        self.processor.gl.get_user_id_cached.return_value = 10843916
        config = {"*": {"protected": True, "allowed_to_create": [{"access_level": 30}]}}
        tag_in_gitlab = _protected_tag(name="*", access_level=40, user_id=10843916)

        diff = self._diff([tag_in_gitlab], config)

        assert "30" in diff
        assert "10843916" in diff
