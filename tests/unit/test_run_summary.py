import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from gitlabform import GitLabForm
from gitlabform.constants import EXIT_PROCESSING_ERROR
from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.run_summary import MACHINE_SUMMARY_PREFIX, RunSummary, run_summary


def _machine_summary(printed: str) -> dict:
    lines = [line for line in printed.splitlines() if line.startswith(MACHINE_SUMMARY_PREFIX)]
    assert len(lines) == 1
    return json.loads(lines[0][len(MACHINE_SUMMARY_PREFIX) :])


def _before_the_machine_summary(printed: str) -> str:
    return printed.split(MACHINE_SUMMARY_PREFIX)[0]


class TestMachineSummaryLine:
    def setup_method(self):
        run_summary.forget()

    def test__a_run_that_touched_nothing_still_says_so_in_one_parsable_line(self, capsys):
        GitLabForm._show_summary(["group_1"], ["group_1/project_1"], 1, 1, {}, {})

        assert _machine_summary(capsys.readouterr().out) == {
            "groups_ok": 1,
            "projects_ok": 1,
            "failed": [],
            "changes": {},
        }

    def test__every_node_that_failed_is_named_in_the_line(self, capsys):
        with pytest.raises(SystemExit) as leaving:
            GitLabForm._show_summary(
                ["group_1", "group_2"],
                ["group_1/project_1", "group_1/project_2"],
                1,
                0,
                {2: "group_2"},
                {1: "group_1/project_1", 2: "group_1/project_2"},
            )

        assert leaving.value.code == EXIT_PROCESSING_ERROR
        assert _machine_summary(capsys.readouterr().out)["failed"] == [
            "group_2",
            "group_1/project_1",
            "group_1/project_2",
        ]

    def test__a_name_longer_than_the_terminal_survives_where_the_human_line_is_torn_in_four(self, capsys):
        name = "group_1/" + "a" * 300

        with pytest.raises(SystemExit):
            GitLabForm._show_summary([], [name], 0, 0, {}, {1: name})

        printed = capsys.readouterr().out
        assert name not in _before_the_machine_summary(printed)
        assert _machine_summary(printed)["failed"] == [name]

    def test__the_sections_that_changed_something_are_named_per_node(self, capsys):
        with run_summary.applying("group_1/project_1", "branches"):
            run_summary.record_write()
        with run_summary.applying("group_1/project_1", "files"):
            run_summary.record_write()
            run_summary.record_write()
        with run_summary.applying("group_1/project_2", "members"):
            run_summary.record_write()

        GitLabForm._show_summary([], ["group_1/project_1", "group_1/project_2"], 0, 2, {}, {})

        assert _machine_summary(capsys.readouterr().out)["changes"] == {
            "group_1/project_1": ["branches", "files"],
            "group_1/project_2": ["members"],
        }

    def test__a_node_the_run_left_alone_is_not_in_changes(self, capsys):
        with run_summary.applying("group_1/project_1", "branches"):
            pass

        GitLabForm._show_summary([], ["group_1/project_1"], 0, 1, {}, {})

        assert _machine_summary(capsys.readouterr().out)["changes"] == {}


class TestWhatCountsAsAChange:
    def setup_method(self):
        self.summary = RunSummary()
        session = requests.Session()
        self.summary.watch(session)
        self.note = session.hooks["response"][-1]

    @staticmethod
    def _answer(method: str, accepted: bool) -> MagicMock:
        response = MagicMock()
        response.request.method = method
        response.ok = accepted
        return response

    def test__a_write_gitlab_accepted_is_a_change(self):
        with self.summary.applying("group_1/project_1", "branches"):
            self.note(self._answer("PUT", True))

        assert self.summary.changes == {"group_1/project_1": ["branches"]}

    def test__a_read_is_not_a_change(self):
        with self.summary.applying("group_1/project_1", "branches"):
            self.note(self._answer("GET", True))

        assert self.summary.changes == {}

    def test__a_write_gitlab_refused_is_not_a_change(self):
        with self.summary.applying("group_1/project_1", "branches"):
            self.note(self._answer("POST", False))

        assert self.summary.changes == {}

    def test__a_write_made_outside_any_section_is_attributed_to_none(self):
        self.note(self._answer("POST", True))

        assert self.summary.changes == {}


class _WritingProcessor(AbstractProcessor):
    def _process_configuration(self, project_or_project_and_group: str, configuration: dict):
        run_summary.record_write()

    def _get_current_state(self, project_or_project_and_group: str) -> dict:
        run_summary.record_write()
        return {}


class _QuietProcessor(AbstractProcessor):
    def _process_configuration(self, project_or_project_and_group: str, configuration: dict):
        pass


class TestTheSectionBeingAppliedIsKnown:
    def setup_method(self):
        run_summary.forget()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = _WritingProcessor("branches", MagicMock())

    def test__a_write_is_attributed_to_the_node_and_section_it_was_made_for(self):
        self.processor.process("group_1/project_1", {"branches": {"main": {}}}, False, False, MagicMock())

        assert run_summary.changes == {"group_1/project_1": ["branches"]}

    def test__a_dry_run_writes_nothing_and_reports_nothing(self):
        self.processor.process("group_1/project_1", {"branches": {"main": {}}}, True, False, MagicMock())

        assert run_summary.changes == {}

    def test__a_write_made_after_a_section_is_done_is_attributed_to_nobody(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            quiet = _QuietProcessor("branches", MagicMock())
        quiet.process("group_1/project_1", {"branches": {"main": {}}}, False, False, MagicMock())

        run_summary.record_write()

        assert run_summary.changes == {}
