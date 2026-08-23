from unittest.mock import MagicMock, patch

import pytest

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.deploy_keys_processor import DeployKeysProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

DEPLOY_KEY_IN_GITLAB = {
    "id": 1,
    "title": "Public key",
    "key": "ssh-rsa AAAA B3NzaC1yc2EAAAABJQAAAIEAiPWx6WM4lhHNedGfBpPJNPpZ7yKu+dnn1SJejgt4596k6YjzGGphH2TUxwKzxcKDKKezwkpfnxPkSMkuEspGRt/aZZ9w",
    "fingerprint": "4a:9d:64:15:ed:3f:c6:de:5f:88:53:e6:65:69:6f:0b",
    "fingerprint_sha256": "SHA256:Jrs3LD1Ji30xNLtTVf9NDCj7kkBgPBb2pjvTZ3HfIgU",
    "created_at": "2013-10-02T10:12:29Z",
    "expires_at": None,
    "can_push": False,
}


def _make_processor() -> DeployKeysProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        gitlab = MagicMock(GitLab)
        gitlab.get_deploy_keys.return_value = [dict(DEPLOY_KEY_IN_GITLAB)]
        return DeployKeysProcessor(gitlab)


class TestDeployKeysDiff:
    def test_state_differs_diff_says_so(self):
        processor = _make_processor()

        current = processor._get_current_state("foo/bar")
        desired = processor._get_desired_state(
            {
                "a_friendly_deploy_key_name": {
                    "title": "Public key",
                    "key": DEPLOY_KEY_IN_GITLAB["key"],
                    "can_push": True,
                }
            }
        )

        text = DifferenceLogger.log_diff("deploy_keys changes", current, desired, only_changed=True, test=True)
        assert "Public key" in text
        assert "true" in text and "false" in text

    def test_state_matches_diff_is_silent(self):
        processor = _make_processor()

        current = processor._get_current_state("foo/bar")
        desired = processor._get_desired_state(
            {
                "a_friendly_deploy_key_name": {
                    "title": "Public key",
                    "key": DEPLOY_KEY_IN_GITLAB["key"],
                    "can_push": False,
                }
            }
        )

        assert DifferenceLogger.log_diff("deploy_keys changes", current, desired, only_changed=True, test=True) == ""

    def test_duplicate_titles_refuse_loudly(self):
        processor = _make_processor()

        with pytest.raises(SystemExit):
            processor._get_desired_state(
                {
                    "one": {"title": "Public key", "key": "ssh-rsa AAA"},
                    "two": {"title": "Public key", "key": "ssh-rsa BBB"},
                }
            )
