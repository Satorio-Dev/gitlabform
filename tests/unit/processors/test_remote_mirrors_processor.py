from unittest.mock import MagicMock, patch

from gitlabform.processors.project.remote_mirrors_processor import RemoteMirrorsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


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
