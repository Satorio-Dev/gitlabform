from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import GitLab
from gitlabform.gitlab.project_freeze_periods import GitLabProjectFreezePeriods
from gitlabform.processors.project.freeze_periods_processor import FreezePeriodsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

PROJECT = "group/project"

WEEKEND_IN_GITLAB: dict[str, Any] = {
    "id": 1,
    "freeze_start": "0 23 * * 5",
    "freeze_end": "0 7 * * 1",
    "cron_timezone": "Europe/Warsaw",
    "created_at": "2020-05-15T17:03:35.702Z",
    "updated_at": "2020-05-15T17:06:41.566Z",
}

RELEASE_REVIEW_IN_GITLAB: dict[str, Any] = {
    "id": 2,
    "freeze_start": "0 18 * * 4",
    "freeze_end": "0 9 * * 5",
    "cron_timezone": "UTC",
    "created_at": "2020-05-15T17:03:35.702Z",
    "updated_at": "2020-05-15T17:06:41.566Z",
}

WEEKEND_IDENTITY = "0 23 * * 5/0 7 * * 1"


def _weekend_in_config(cron_timezone: str = "Europe/Warsaw") -> dict[str, Any]:
    return {
        "freeze_start": "0 23 * * 5",
        "freeze_end": "0 7 * * 1",
        "cron_timezone": cron_timezone,
    }


def _make_processor(freeze_periods_in_gitlab: list) -> FreezePeriodsProcessor:
    gitlab_mock = MagicMock(GitLab)
    gitlab_mock.get_freeze_periods.return_value = freeze_periods_in_gitlab
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        return FreezePeriodsProcessor(gitlab_mock)


def _add(processor: FreezePeriodsProcessor) -> MagicMock:
    return cast(MagicMock, processor.add_method)


def _edit(processor: FreezePeriodsProcessor) -> MagicMock:
    return cast(MagicMock, processor.edit_method)


def _delete(processor: FreezePeriodsProcessor) -> MagicMock:
    return cast(MagicMock, processor.delete_method)


def _writes(processor: FreezePeriodsProcessor) -> dict[str, int]:
    return {
        "add": _add(processor).call_count,
        "edit": _edit(processor).call_count if processor.edit_method else 0,
        "delete": _delete(processor).call_count,
    }


class TestFreezePeriodsApply:
    def test_a_declared_period_gitlab_has_not_got_is_created(self) -> None:
        processor = _make_processor([])

        processor._process_configuration(PROJECT, {"freeze_periods": {"weekend": _weekend_in_config()}})

        _add(processor).assert_called_once_with(PROJECT, _weekend_in_config())
        assert _writes(processor) == {"add": 1, "edit": 0, "delete": 0}

    def test_a_declared_period_gitlab_already_has_is_not_created_again(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        processor._process_configuration(PROJECT, {"freeze_periods": {"weekend": _weekend_in_config()}})

        _add(processor).assert_not_called()

    def test_enforce_deletes_a_period_the_configuration_does_not_declare(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB, RELEASE_REVIEW_IN_GITLAB])

        processor._process_configuration(
            PROJECT,
            {"freeze_periods": {"weekend": _weekend_in_config(), "enforce": True}},
        )

        _delete(processor).assert_called_once_with(PROJECT, RELEASE_REVIEW_IN_GITLAB)
        assert _writes(processor) == {"add": 0, "edit": 0, "delete": 1}

    def test_without_enforce_a_period_the_configuration_does_not_declare_stays(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB, RELEASE_REVIEW_IN_GITLAB])

        processor._process_configuration(PROJECT, {"freeze_periods": {"weekend": _weekend_in_config()}})

        assert _writes(processor) == {"add": 0, "edit": 0, "delete": 0}

    def test_an_unchanged_period_writes_nothing(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        processor._process_configuration(
            PROJECT,
            {"freeze_periods": {"weekend": _weekend_in_config(), "enforce": True}},
        )

        assert _writes(processor) == {"add": 0, "edit": 0, "delete": 0}

    def test_a_changed_timezone_is_edited_in_place(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        processor._process_configuration(
            PROJECT,
            {"freeze_periods": {"weekend": _weekend_in_config(cron_timezone="Asia/Tokyo")}},
        )

        _edit(processor).assert_called_once_with(
            PROJECT, WEEKEND_IN_GITLAB, _weekend_in_config(cron_timezone="Asia/Tokyo")
        )
        assert _writes(processor) == {"add": 0, "edit": 1, "delete": 0}

    def test_a_period_marked_for_deletion_is_deleted(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        processor._process_configuration(
            PROJECT,
            {"freeze_periods": {"weekend": {**_weekend_in_config(), "delete": True}}},
        )

        _delete(processor).assert_called_once_with(PROJECT, WEEKEND_IN_GITLAB)
        assert _writes(processor) == {"add": 0, "edit": 0, "delete": 1}


def _render_diff(processor: FreezePeriodsProcessor, entity_config: dict) -> str:
    return DifferenceLogger.log_diff(
        "freeze_periods changes",
        processor._get_current_state(PROJECT),
        processor._get_desired_state(entity_config),
        only_changed=True,
        test=True,
    )


def _print_diff(processor: FreezePeriodsProcessor, entity_config: dict, caplog) -> str:
    with caplog.at_level("INFO"):
        processor._print_diff(PROJECT, entity_config, diff_only_changed=True)
    return "\n".join(record.message for record in caplog.records if "freeze_periods changes" in record.message)


class TestFreezePeriodsDiff:
    def test_the_diff_is_silent_when_the_state_matches(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        assert _render_diff(processor, {"weekend": _weekend_in_config()}) == ""

    def test_the_server_side_timestamps_are_not_a_difference(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        current = processor._get_current_state(PROJECT)

        assert current == {
            WEEKEND_IDENTITY: {
                "cron_timezone": "Europe/Warsaw",
                "freeze_end": "0 7 * * 1",
                "freeze_start": "0 23 * * 5",
            }
        }

    def test_the_diff_names_both_timezones_when_the_timezone_changes(self) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        diff = _render_diff(processor, {"weekend": _weekend_in_config(cron_timezone="Asia/Tokyo")})

        assert WEEKEND_IDENTITY in diff
        assert "Europe/Warsaw" in diff
        assert "Asia/Tokyo" in diff

    def test_a_rewritten_cron_reads_as_one_period_going_and_another_coming(self, caplog) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        diff = _print_diff(
            processor,
            {
                "weekend": {
                    "freeze_start": "0 22 * * 5",
                    "freeze_end": "0 7 * * 1",
                    "cron_timezone": "Europe/Warsaw",
                },
                "enforce": True,
            },
            caplog,
        )

        assert "0 22 * * 5/0 7 * * 1" in diff
        assert WEEKEND_IDENTITY in diff
        assert "(will be removed by enforce)" in diff

    def test_a_period_only_in_gitlab_reads_as_only_in_gitlab_without_enforce(self, caplog) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        diff = _print_diff(processor, {}, caplog)

        assert WEEKEND_IDENTITY in diff
        assert "(only in GitLab)" in diff
        assert "(will be removed by enforce)" not in diff

    def test_a_period_marked_for_deletion_reads_as_a_deletion(self, caplog) -> None:
        processor = _make_processor([WEEKEND_IN_GITLAB])

        diff = _print_diff(processor, {"weekend": {**_weekend_in_config(), "delete": True}}, caplog)

        assert WEEKEND_IDENTITY in diff
        assert "(will be deleted)" in diff


class TestFreezePeriodsIdentityIsRefusedWhenAmbiguous:
    def test_two_labels_declaring_the_same_pair_of_crons_are_refused(self) -> None:
        processor = _make_processor([])

        with pytest.raises(SystemExit) as exit_info:
            processor._get_desired_state({"weekend": _weekend_in_config(), "also_weekend": _weekend_in_config("UTC")})

        assert exit_info.value.code == EXIT_INVALID_INPUT

    def test_a_period_that_does_not_declare_both_crons_is_refused(self) -> None:
        processor = _make_processor([])

        with pytest.raises(SystemExit) as exit_info:
            processor._get_desired_state({"weekend": {"freeze_start": "0 23 * * 5"}})

        assert exit_info.value.code == EXIT_INVALID_INPUT

    def test_the_refusal_names_both_labels(self, caplog) -> None:
        processor = _make_processor([])

        with caplog.at_level("CRITICAL"), pytest.raises(SystemExit):
            processor._get_desired_state({"weekend": _weekend_in_config(), "also_weekend": _weekend_in_config("UTC")})

        assert "weekend" in caplog.text
        assert "also_weekend" in caplog.text


class TestFreezePeriodsEndpoints:
    @staticmethod
    def _api() -> GitLabProjectFreezePeriods:
        api = GitLabProjectFreezePeriods.__new__(GitLabProjectFreezePeriods)
        api._make_requests_to_api = MagicMock()  # type: ignore[method-assign]
        return api

    @staticmethod
    def _requests(api: GitLabProjectFreezePeriods) -> MagicMock:
        return cast(MagicMock, api._make_requests_to_api)

    def test_the_list_read_is_the_freeze_periods_endpoint_of_the_project(self) -> None:
        api = self._api()

        api.get_freeze_periods(PROJECT)

        self._requests(api).assert_called_once_with("projects/%s/freeze_periods", PROJECT)

    def test_a_key_the_api_does_not_have_does_not_travel_to_it(self) -> None:
        api = self._api()

        api.add_freeze_period(PROJECT, {**_weekend_in_config(), "delete": False})

        self._requests(api).assert_called_once_with(
            "projects/%s/freeze_periods",
            PROJECT,
            method="POST",
            data=_weekend_in_config(),
            expected_codes=201,
        )

    def test_an_edit_addresses_the_period_by_the_id_gitlab_gave_it(self) -> None:
        api = self._api()

        api.edit_freeze_period(PROJECT, WEEKEND_IN_GITLAB, _weekend_in_config(cron_timezone="Asia/Tokyo"))

        self._requests(api).assert_called_once_with(
            "projects/%s/freeze_periods/%s",
            (PROJECT, 1),
            method="PUT",
            data=_weekend_in_config(cron_timezone="Asia/Tokyo"),
        )

    def test_a_period_already_gone_is_an_accepted_delete(self) -> None:
        api = self._api()

        api.delete_freeze_period(PROJECT, WEEKEND_IN_GITLAB)

        self._requests(api).assert_called_once_with(
            "projects/%s/freeze_periods/%s",
            (PROJECT, 1),
            method="DELETE",
            expected_codes=[200, 204, 404],
        )
