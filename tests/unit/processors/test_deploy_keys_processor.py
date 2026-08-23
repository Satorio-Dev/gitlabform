from unittest.mock import MagicMock, patch

import pytest

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.deploy_keys_processor import DeployKeysProcessor

DEPLOY_KEY_IN_GITLAB = {
    "id": 1,
    "title": "Public key",
    "key": "ssh-rsa AAAA B3NzaC1yc2EAAAABJQAAAIEAiPWx6WM4lhHNedGfBpPJNPpZ7yKu+dnn1SJejgt4596k6YjzGGphH2TUxwKzxcKDKKezwkpfnxPkSMkuEspGRt/aZZ9w",
    "fingerprint": "4a:9d:64:15:ed:3f:c6:de:5f:88:53:e6:65:69:6f:0b",
    "fingerprint_sha256": "SHA256:Jrs3LD1Ji30xNLtTVf9NDCj7kkBgPBb2pjvTZ3HfIgU",
    "created_at": "2013-10-02T10:12:29Z",
    "last_used_at": "2026-08-21T09:41:07Z",
    "expires_at": None,
    "can_push": False,
    "usage_type": "auth",
}


def _make_processor() -> DeployKeysProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        gitlab = MagicMock(GitLab)
        gitlab.get_deploy_keys.return_value = [dict(DEPLOY_KEY_IN_GITLAB)]
        return DeployKeysProcessor(gitlab)


def _diff(processor: DeployKeysProcessor, config: dict, caplog) -> str:
    with caplog.at_level("INFO"):
        processor._print_diff("foo/bar", config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if "deploy_keys changes" in r.message)


def _config(**overrides) -> dict:
    key = {"title": "Public key", "key": DEPLOY_KEY_IN_GITLAB["key"], "can_push": False}
    key.update(overrides)
    return {"a_friendly_deploy_key_name": key}


class TestDeployKeysDiff:
    def test_state_differs_diff_says_so(self, caplog):
        text = _diff(_make_processor(), _config(can_push=True), caplog)

        assert "Public key" in text
        assert "true" in text and "false" in text

    def test_state_matches_diff_is_silent(self, caplog):
        assert _diff(_make_processor(), _config(), caplog) == ""

    def test_last_used_at_never_reaches_the_diff(self):
        assert "last_used_at" not in _make_processor()._get_current_state("foo/bar")["Public key"]

    def test_usage_type_is_not_a_difference_unless_the_config_declares_it(self, caplog):
        assert "usage_type" not in _diff(_make_processor(), _config(), caplog)

    def test_usage_type_is_compared_when_the_config_does_declare_it(self, caplog):
        text = _diff(_make_processor(), _config(usage_type="auth_and_signing"), caplog)

        assert "auth_and_signing" in text

    def test_key_only_in_gitlab_is_reported_as_removed_by_enforce(self, caplog):
        config = _config(title="Another key")
        config["enforce"] = True

        text = _diff(_make_processor(), config, caplog)

        assert "Public key" in text
        assert "(will be removed by enforce)" in text

    def test_duplicate_titles_refuse_loudly(self):
        processor = _make_processor()

        with pytest.raises(SystemExit):
            processor._get_desired_state(
                {
                    "one": {"title": "Public key", "key": "ssh-rsa AAA"},
                    "two": {"title": "Public key", "key": "ssh-rsa BBB"},
                }
            )
