from unittest.mock import MagicMock, patch

from gitlabform.processors.project.schedules_processor import SchedulesProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _gitlab_schedule(schedule_id=13, description="Test schedule pipeline", cron="0 1 * * 5", active=True):
    """A realistic body of GET /projects/:id/pipeline_schedules/:pipeline_schedule_id."""
    return {
        "id": schedule_id,
        "description": description,
        "ref": "refs/heads/main",
        "cron": cron,
        "cron_timezone": "Asia/Tokyo",
        "next_run_at": "2024-05-19T13:41:00.000Z",
        "active": active,
        "created_at": "2024-05-19T13:31:08.849Z",
        "updated_at": "2024-05-19T13:40:17.727Z",
        "owner": {"name": "Administrator", "username": "root", "id": 1},
        "variables": [{"key": "TEST_VARIABLE_1", "variable_type": "env_var", "value": "TEST_1", "raw": False}],
    }


def _configured_schedule(cron="0 1 * * 5"):
    return {
        "ref": "refs/heads/main",
        "cron": cron,
        "cron_timezone": "Asia/Tokyo",
        "active": True,
        "variables": {"TEST_VARIABLE_1": {"variable_type": "env_var", "value": "TEST_1", "raw": False}},
    }


class TestSchedulesDiff:
    def setup_method(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = SchedulesProcessor(MagicMock())
        self.project = MagicMock()
        self.processor.gl.get_project_by_path_cached.return_value = self.project

    def _set_gitlab_schedules(self, schedules):
        listed = []
        full_by_id = {}
        for schedule in schedules:
            item = MagicMock()
            item.id = schedule["id"]
            listed.append(item)
            full = MagicMock()
            full.asdict.return_value = schedule
            full_by_id[schedule["id"]] = full
        self.project.pipelineschedules.list.return_value = listed
        self.project.pipelineschedules.get.side_effect = lambda schedule_id: full_by_id[schedule_id]

    def _diff(self, gitlab_schedules, configured_schedules):
        self._set_gitlab_schedules(gitlab_schedules)
        return DifferenceLogger.log_diff(
            "schedules changes",
            self.processor._get_current_state("group/project"),
            self.processor._get_desired_state(configured_schedules),
            only_changed=True,
            test=True,
        )

    def test_no_diff_when_state_matches(self):
        config = {"Test schedule pipeline": _configured_schedule()}
        assert self._diff([_gitlab_schedule()], config) == ""

    def test_diff_names_the_schedule_when_cron_differs(self):
        config = {"Test schedule pipeline": _configured_schedule(cron="0 2 * * 5")}
        diff = self._diff([_gitlab_schedule(cron="0 1 * * 5")], config)
        assert "Test schedule pipeline" in diff
        assert "0 1 * * 5" in diff
        assert "0 2 * * 5" in diff

    def test_variables_come_from_the_per_id_read(self):
        self._set_gitlab_schedules([_gitlab_schedule()])
        current = self.processor._get_current_state("group/project")
        assert current["Test schedule pipeline"]["variables"] == {
            "TEST_VARIABLE_1": {"variable_type": "env_var", "value": "TEST_1", "raw": False}
        }

    def test_duplicate_descriptions_are_shown_as_a_list(self):
        self._set_gitlab_schedules([_gitlab_schedule(schedule_id=13), _gitlab_schedule(schedule_id=14, active=False)])
        current = self.processor._get_current_state("group/project")
        assert isinstance(current["Test schedule pipeline"], list)
        assert len(current["Test schedule pipeline"]) == 2

    def _print_diff(self, gitlab_schedules, configured_schedules, caplog) -> str:
        self._set_gitlab_schedules(gitlab_schedules)
        with caplog.at_level("INFO"):
            self.processor._print_diff("group/project", configured_schedules, diff_only_changed=True)
        return "\n".join(r.message for r in caplog.records if "schedules changes" in r.message)

    def test_schedule_marked_for_delete_reads_as_a_deletion(self, caplog):
        diff = self._print_diff([_gitlab_schedule()], {"Test schedule pipeline": {"delete": True}}, caplog)

        assert "Test schedule pipeline" in diff
        assert "(will be deleted)" in diff

    def test_schedule_marked_for_delete_that_does_not_exist_is_not_promised_a_deletion(self, caplog):
        diff = self._print_diff([_gitlab_schedule()], {"Other schedule": {"delete": True}}, caplog)

        assert "Other schedule" in diff
        assert "(not in GitLab - nothing to delete)" in diff
        assert "(will be deleted)" not in diff
