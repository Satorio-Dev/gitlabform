from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.group.group_variables_processor import GroupVariablesProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

VARIABLE_IN_GITLAB = {
    "variable_type": "env_var",
    "key": "TEST_VARIABLE_1",
    "value": "TEST_1",
    "protected": False,
    "masked": False,
    "raw": False,
    "environment_scope": "*",
    "description": None,
}

VARIABLE_IN_CONFIG = {
    "key": "TEST_VARIABLE_1",
    "value": "TEST_1",
    "variable_type": "env_var",
    "protected": False,
    "masked": False,
    "raw": False,
    "environment_scope": "*",
    "description": None,
}


def _make_processor() -> GroupVariablesProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = GroupVariablesProcessor(MagicMock(GitLab))
    variable = MagicMock()
    variable.asdict.return_value = dict(VARIABLE_IN_GITLAB)
    processor.gl = MagicMock()
    processor.gl.get_group_by_path_cached.return_value.variables.list.return_value = [variable]
    return processor


class TestGroupVariablesDiff:
    def test_state_differs_diff_says_so_without_leaking_values(self):
        processor = _make_processor()

        current = processor._get_current_state("foo")
        desired = processor._get_desired_state(
            {"enforce": True, "my_variable": {**VARIABLE_IN_CONFIG, "value": "CHANGED"}}
        )

        text = DifferenceLogger.log_diff("group_variables changes", current, desired, only_changed=True, test=True)
        assert "TEST_VARIABLE_1@*" in text
        assert "TEST_1" not in text
        assert "CHANGED" not in text
        assert "<secret " in text

    def test_state_matches_diff_is_silent(self):
        processor = _make_processor()

        current = processor._get_current_state("foo")
        desired = processor._get_desired_state({"enforce": True, "my_variable": dict(VARIABLE_IN_CONFIG)})

        assert (
            DifferenceLogger.log_diff("group_variables changes", current, desired, only_changed=True, test=True) == ""
        )

    def test_same_key_on_two_scopes_are_two_entities(self):
        processor = _make_processor()

        desired = processor._get_desired_state(
            {
                "staging": {"key": "DB_URL", "value": "a", "environment_scope": "staging"},
                "production": {"key": "DB_URL", "value": "b", "environment_scope": "production"},
            }
        )

        assert set(desired.keys()) == {"DB_URL@staging", "DB_URL@production"}
