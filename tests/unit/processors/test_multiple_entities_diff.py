from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.group.group_ldap_links_processor import GroupLDAPLinksProcessor
from gitlabform.processors.project.badges_processor import BadgesProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _render_diff(processor, project_or_group: str, entity_config: dict) -> str:
    current = processor._get_current_state(project_or_group)
    desired = processor._get_desired_state(entity_config)
    return DifferenceLogger.log_diff("changes", current, desired, only_changed=True, test=True)


BADGE_IN_GITLAB = {
    "id": 1,
    "name": "Coverage",
    "link_url": "http://example.com/ci_status.svg?project=%{project_path}&ref=%{default_branch}",
    "image_url": "https://shields.io/my/badge",
    "rendered_link_url": "http://example.com/ci_status.svg?project=example-org/example-project&ref=master",
    "rendered_image_url": "https://shields.io/my/badge",
    "kind": "project",
}


class TestBadgesDiff:
    def _make_processor(self, badges_in_gitlab: list) -> BadgesProcessor:
        gitlab_mock = MagicMock(GitLab)
        gitlab_mock.get_project_badges.return_value = badges_in_gitlab
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            return BadgesProcessor(gitlab_mock)

    def test__diff_reports_difference(self) -> None:
        processor = self._make_processor([BADGE_IN_GITLAB])

        diff = _render_diff(
            processor,
            "group/project",
            {
                "coverage": {
                    "name": "Coverage",
                    "link_url": BADGE_IN_GITLAB["link_url"],
                    "image_url": "https://shields.io/my/other-badge",
                }
            },
        )

        assert "Coverage" in diff
        assert "https://shields.io/my/other-badge" in diff

    def test__diff_is_silent_when_state_matches(self) -> None:
        processor = self._make_processor([BADGE_IN_GITLAB])

        diff = _render_diff(
            processor,
            "group/project",
            {
                "coverage": {
                    "name": "Coverage",
                    "link_url": BADGE_IN_GITLAB["link_url"],
                    "image_url": BADGE_IN_GITLAB["image_url"],
                }
            },
        )

        assert diff == ""


LDAP_LINK_IN_GITLAB = {
    "cn": "gitlab_community",
    "group_access": 30,
    "provider": "ldapmain",
    "filter": None,
}


class TestGroupLDAPLinksDiff:
    def _make_processor(self, links_in_gitlab: list) -> GroupLDAPLinksProcessor:
        gitlab_mock = MagicMock(GitLab)
        gitlab_mock.get_ldap_group_links.return_value = links_in_gitlab
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            return GroupLDAPLinksProcessor(gitlab_mock)

    def test__diff_reports_difference(self) -> None:
        processor = self._make_processor([LDAP_LINK_IN_GITLAB])

        diff = _render_diff(
            processor,
            "some_group",
            {"community": {"provider": "ldapmain", "cn": "gitlab_community", "group_access": 50}},
        )

        assert "gitlab_community" in diff
        assert "50" in diff

    def test__diff_is_silent_when_state_matches(self) -> None:
        processor = self._make_processor([LDAP_LINK_IN_GITLAB])

        diff = _render_diff(
            processor,
            "some_group",
            {"community": {"provider": "ldapmain", "cn": "gitlab_community", "group_access": 30}},
        )

        assert diff == ""

    def test__entities_are_keyed_by_composite_defining_key(self) -> None:
        processor = self._make_processor(
            [
                LDAP_LINK_IN_GITLAB,
                {"cn": None, "group_access": 10, "provider": "ldapmain", "filter": "(memberOf=cn=x)"},
            ]
        )

        current = processor._get_current_state("some_group")

        assert set(current.keys()) == {"ldapmain/gitlab_community", "ldapmain/(memberOf=cn=x)"}


def _print_diff(processor, project_or_group: str, entity_config: dict, caplog) -> str:
    """Goes through _print_diff(), unlike _render_diff() above: what the config marks
    for deletion is reconciled against GitLab there, with both sides in hand."""
    with caplog.at_level("INFO"):
        processor._print_diff(project_or_group, entity_config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if "changes" in r.message)


class TestMultipleEntitiesDeleteFlag:
    @staticmethod
    def _make_processor(badges_in_gitlab: list) -> BadgesProcessor:
        gitlab_mock = MagicMock(GitLab)
        gitlab_mock.get_project_badges.return_value = badges_in_gitlab
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            return BadgesProcessor(gitlab_mock)

    def test_a_badge_marked_for_deletion_reads_as_a_deletion(self, caplog) -> None:
        processor = self._make_processor([BADGE_IN_GITLAB])

        diff = _print_diff(processor, "group/project", {"coverage": {"name": "Coverage", "delete": True}}, caplog)

        assert "Coverage" in diff
        assert "(will be deleted)" in diff

    def test_a_badge_marked_for_deletion_that_gitlab_has_not_got_is_still_an_addition(self, caplog) -> None:
        processor = self._make_processor([])

        diff = _print_diff(
            processor,
            "group/project",
            {
                "coverage": {
                    "name": "Coverage",
                    "link_url": "http://e.com/b",
                    "image_url": "http://e.com/i",
                    "delete": True,
                }
            },
            caplog,
        )

        assert "Coverage" in diff
        assert "(will be deleted)" not in diff
        assert "http://e.com/i" in diff
        assert "not in GitLab" not in diff

    def test_a_badge_the_config_applies_is_untouched_by_the_marker(self, caplog) -> None:
        processor = self._make_processor([BADGE_IN_GITLAB])

        diff = _print_diff(
            processor,
            "group/project",
            {
                "coverage": {
                    "name": "Coverage",
                    "link_url": BADGE_IN_GITLAB["link_url"],
                    "image_url": "https://shields.io/my/other-badge",
                }
            },
            caplog,
        )

        assert "https://shields.io/my/other-badge" in diff
        assert "(will be deleted)" not in diff
