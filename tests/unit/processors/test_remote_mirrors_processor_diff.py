from typing import cast
from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.project.remote_mirrors_processor import RemoteMirrorsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

MIRROR_IN_GITLAB = {
    "enabled": True,
    "id": 101486,
    "auth_method": "password",
    "last_error": None,
    "last_successful_update_at": "2020-01-06T17:32:02.823Z",
    "last_update_at": "2020-01-06T17:32:02.823Z",
    "last_update_started_at": "2020-01-06T17:31:55.864Z",
    "only_protected_branches": True,
    "keep_divergent_refs": True,
    "update_status": "finished",
    "url": "https://*****:*****@gitlab.com/gitlab-org/security/gitlab.git",
}

MIRROR_URL_IN_CONFIG = "https://user:s3cret@gitlab.com/gitlab-org/security/gitlab.git"

MIRROR_CONFIG = {
    "enabled": True,
    "auth_method": "password",
    "only_protected_branches": True,
    "keep_divergent_refs": True,
}


def _make_processor(mirror_in_gitlab: dict) -> RemoteMirrorsProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = RemoteMirrorsProcessor(MagicMock(GitLab))

    mirror = MagicMock()
    mirror.url = mirror_in_gitlab["url"]
    mirror.asdict.return_value = mirror_in_gitlab

    project = cast(MagicMock, processor.gl).get_project_by_path_cached.return_value
    project.remote_mirrors.list.return_value = [mirror]

    return processor


def _render_diff(processor, entity_config: dict) -> str:
    current = processor._get_current_state("group/project")
    desired = processor._get_desired_state(entity_config)
    return DifferenceLogger.log_diff("changes", current, desired, only_changed=True, test=True)


class TestRemoteMirrorsDiff:
    def test__diff_reports_difference(self) -> None:
        processor = _make_processor(MIRROR_IN_GITLAB)

        diff = _render_diff(
            processor,
            {"enforce": True, MIRROR_URL_IN_CONFIG: {**MIRROR_CONFIG, "only_protected_branches": False}},
        )

        assert "only_protected_branches" in diff

    def test__diff_is_silent_when_state_matches(self) -> None:
        processor = _make_processor(MIRROR_IN_GITLAB)

        diff = _render_diff(processor, {"enforce": True, MIRROR_URL_IN_CONFIG: MIRROR_CONFIG})

        assert diff == ""

    def test__credentials_do_not_leak_into_the_diff(self) -> None:
        processor = _make_processor(MIRROR_IN_GITLAB)

        diff = _render_diff(
            processor,
            {MIRROR_URL_IN_CONFIG: {**MIRROR_CONFIG, "enabled": False}},
        )

        assert "enabled" in diff
        assert "s3cret" not in diff

    def test__local_only_action_flags_are_not_diffed(self) -> None:
        processor = _make_processor(MIRROR_IN_GITLAB)

        diff = _render_diff(
            processor,
            {MIRROR_URL_IN_CONFIG: {**MIRROR_CONFIG, "force_push": True, "print_public_key": True}},
        )

        assert diff == ""


def _print_diff(processor, entity_config: dict, caplog) -> str:
    """Goes through _print_diff(), unlike _render_diff() above: what the config marks
    for deletion is reconciled against GitLab there, with both sides in hand."""
    with caplog.at_level("INFO"):
        processor._print_diff("group/project", entity_config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if "remote_mirrors changes" in r.message)


class TestRemoteMirrorsDeleteFlag:
    def test_a_mirror_marked_for_deletion_reads_as_a_deletion(self, caplog) -> None:
        processor = _make_processor(MIRROR_IN_GITLAB)

        diff = _print_diff(processor, {MIRROR_URL_IN_CONFIG: {"delete": True}}, caplog)

        assert "(will be deleted)" in diff

    def test_a_mirror_gitlab_has_not_got_is_not_promised_a_deletion(self, caplog) -> None:
        processor = _make_processor(MIRROR_IN_GITLAB)

        diff = _print_diff(processor, {"https://gitlab.com/other/repo.git": {"delete": True}}, caplog)

        assert "https://gitlab.com/other/repo.git" in diff
        assert "(not in GitLab - nothing to delete)" in diff
        assert "(will be deleted)" not in diff
