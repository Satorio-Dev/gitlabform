from unittest.mock import MagicMock, patch

import pytest
from gitlab.exceptions import GitlabCreateError, GitlabDeleteError, GitlabUpdateError

from gitlabform.processors.project.remote_mirrors_processor import RemoteMirrorsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger
from gitlabform.processors.util.failed_writes import SomeWritesFailed


def _diff(current: dict, desired: dict) -> str:
    return DifferenceLogger.log_diff("remote_mirrors changes", current, desired, only_changed=True, test=True)


class TestRemoteMirrorsProcessorDryRunDiff:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = RemoteMirrorsProcessor(self.gitlab)
        self.processor.gl = MagicMock()

    def _mock_mirror(self, url, enabled=True, only_protected_branches=True):
        mirror = MagicMock()
        mirror.asdict.return_value = {
            "enabled": enabled,
            "id": 101486,
            "auth_method": "password",
            "last_error": None,
            "last_successful_update_at": "2020-01-06T17:32:02.823Z",
            "last_update_at": "2020-01-06T17:32:02.823Z",
            "last_update_started_at": "2020-01-06T17:31:55.864Z",
            "only_protected_branches": only_protected_branches,
            "keep_divergent_refs": True,
            "update_status": "finished",
            "url": url,
        }
        return mirror

    def test__differing_flag_shows_in_diff(self):
        project = self.processor.gl.get_project_by_path_cached.return_value
        project.remote_mirrors.list.return_value = [
            self._mock_mirror("https://github.com/gitlab-org/security/gitlab.git", only_protected_branches=True)
        ]
        config = {
            "https://github.com/gitlab-org/security/gitlab.git": {
                "enabled": True,
                "auth_method": "password",
                "only_protected_branches": False,
                "keep_divergent_refs": True,
            }
        }

        text = _diff(
            self.processor._get_current_state("foo/bar"),
            self.processor._get_desired_state(config),
        )

        assert "github.com" in text
        assert "false" in text.lower()

    def test__matching_state_without_credentials_is_silent(self):
        project = self.processor.gl.get_project_by_path_cached.return_value
        project.remote_mirrors.list.return_value = [
            self._mock_mirror("https://github.com/gitlab-org/security/gitlab.git")
        ]
        config = {
            "https://github.com/gitlab-org/security/gitlab.git": {
                "enabled": True,
                "auth_method": "password",
                "only_protected_branches": True,
                "keep_divergent_refs": True,
            }
        }

        assert (
            _diff(
                self.processor._get_current_state("foo/bar"),
                self.processor._get_desired_state(config),
            )
            == ""
        )

    def test__credentials_are_not_diffed_and_never_leak(self):
        project = self.processor.gl.get_project_by_path_cached.return_value
        project.remote_mirrors.list.return_value = [
            self._mock_mirror("https://*****:*****@github.com/gitlab-org/security/gitlab.git")
        ]
        config = {
            "https://user:token@github.com/gitlab-org/security/gitlab.git": {
                "enabled": True,
                "auth_method": "password",
                "only_protected_branches": True,
                "keep_divergent_refs": True,
            }
        }

        current = self.processor._get_current_state("foo/bar")
        desired = self.processor._get_desired_state(config)
        text = _diff(current, desired)

        assert text == ""
        assert "user:token" not in str(current) + str(desired)

    def test__action_and_global_keys_are_not_part_of_the_desired_state(self):
        desired = self.processor._get_desired_state(
            {
                "enforce": True,
                "print_details": True,
                "https://github.com/gitlab-org/security/gitlab.git": {
                    "enabled": True,
                    "force_push": True,
                    "force_update": True,
                    "print_public_key": True,
                },
            }
        )

        assert desired == {
            "https://github.com/gitlab-org/security/gitlab.git": {
                "enabled": True,
                "url": "https://github.com/gitlab-org/security/gitlab.git",
            }
        }


class TestRemoteMirrorsProcessorFailedWrites:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = RemoteMirrorsProcessor(self.gitlab)
        self.processor.gl = MagicMock()
        self.project = self.processor.gl.get_project_by_path_cached.return_value

    @staticmethod
    def _mirror(url, enabled=True):
        mirror = MagicMock()
        mirror.url = url
        mirror.id = 101486
        mirror.asdict.return_value = {"id": 101486, "enabled": enabled, "url": url}
        return mirror

    def test__a_create_gitlab_refuses_fails_the_node_and_the_other_mirrors_are_still_written(self):
        self.project.remote_mirrors.list.return_value = []
        self.project.remote_mirrors.create.side_effect = [GitlabCreateError("no", 400), MagicMock()]

        with pytest.raises(SomeWritesFailed) as failure:
            self.processor._process_configuration(
                "foo/bar",
                {
                    "remote_mirrors": {
                        "https://a.example.com/one.git": {"enabled": True},
                        "https://b.example.com/two.git": {"enabled": True},
                    }
                },
            )

        assert self.project.remote_mirrors.create.call_count == 2
        assert "a.example.com" in str(failure.value)
        assert "b.example.com" not in str(failure.value)
        assert "foo/bar" in str(failure.value)

    def test__an_update_gitlab_refuses_fails_the_node(self):
        url = "https://a.example.com/one.git"
        self.project.remote_mirrors.list.return_value = [self._mirror(url, enabled=True)]
        self.project.remote_mirrors.update.side_effect = GitlabUpdateError("no", 400)

        with pytest.raises(SomeWritesFailed) as failure:
            self.processor._process_configuration("foo/bar", {"remote_mirrors": {url: {"enabled": False}}})

        assert "Failed to update remote mirror" in str(failure.value)

    def test__a_delete_gitlab_refuses_fails_the_node(self):
        url = "https://a.example.com/one.git"
        mirror = self._mirror(url)
        mirror.delete.side_effect = GitlabDeleteError("no", 400)
        self.project.remote_mirrors.list.return_value = [mirror]

        with pytest.raises(SomeWritesFailed) as failure:
            self.processor._process_configuration("foo/bar", {"remote_mirrors": {url: {"delete": True}}})

        assert "Failed to delete remote mirror" in str(failure.value)

    def test__a_sync_gitlab_refuses_fails_the_node(self):
        url = "https://a.example.com/one.git"
        created = self._mirror(url)
        created.sync.side_effect = GitlabCreateError("no", 400)
        self.project.remote_mirrors.list.return_value = []
        self.project.remote_mirrors.create.return_value = created

        with pytest.raises(SomeWritesFailed) as failure:
            self.processor._process_configuration(
                "foo/bar", {"remote_mirrors": {url: {"enabled": True, "force_push": True}}}
            )

        assert "Failed to trigger sync" in str(failure.value)

    def test__mirrors_gitlab_accepts_leave_the_node_green(self):
        self.project.remote_mirrors.list.return_value = []

        self.processor._process_configuration(
            "foo/bar", {"remote_mirrors": {"https://a.example.com/one.git": {"enabled": True}}}
        )

        assert self.project.remote_mirrors.create.call_count == 1

    def test__what_one_node_refused_is_not_carried_into_the_next(self):
        self.project.remote_mirrors.list.return_value = []
        self.project.remote_mirrors.create.side_effect = GitlabCreateError("no", 400)
        with pytest.raises(SomeWritesFailed):
            self.processor._process_configuration(
                "foo/bar", {"remote_mirrors": {"https://a.example.com/one.git": {"enabled": True}}}
            )

        self.project.remote_mirrors.create.side_effect = None
        self.processor._process_configuration(
            "foo/baz", {"remote_mirrors": {"https://a.example.com/one.git": {"enabled": True}}}
        )
