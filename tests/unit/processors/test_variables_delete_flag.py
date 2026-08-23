from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors.group.group_variables_processor import GroupVariablesProcessor
from gitlabform.processors.project.project_variables_processor import ProjectVariablesProcessor

VARIABLE_IN_GITLAB = {
    "variable_type": "env_var",
    "key": "TEST_VARIABLE_1",
    "value": "TEST_1",
    "protected": False,
    "masked": False,
    "raw": False,
    "environment_scope": "*",
}


def _project_processor(variables_in_gitlab: list):
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = ProjectVariablesProcessor(MagicMock(GitLab), log_level=0)
    processor.gl = MagicMock()
    processor.gl.get_project_by_path_cached.return_value.variables.list.return_value = variables_in_gitlab
    return processor


def _group_processor(variables_in_gitlab: list):
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = GroupVariablesProcessor(MagicMock(GitLab))
    processor.gl = MagicMock()
    processor.gl.get_group_by_path_cached.return_value.variables.list.return_value = variables_in_gitlab
    return processor


def _variable(**overrides):
    variable = MagicMock()
    variable.asdict.return_value = {**VARIABLE_IN_GITLAB, **overrides}
    return variable


def _diff(processor, section: str, entity_config: dict, caplog) -> str:
    with caplog.at_level("INFO"):
        processor._print_diff("group/project", entity_config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if f"{section} changes" in r.message)


class TestVariablesDeleteFlag:
    def test_project_variable_marked_for_deletion_reads_as_a_deletion(self, caplog):
        processor = _project_processor([_variable()])

        diff = _diff(processor, "variables", {"one": {"key": "TEST_VARIABLE_1", "delete": True}}, caplog)

        assert "TEST_VARIABLE_1@*" in diff
        assert "(will be deleted)" in diff

    def test_group_variable_marked_for_deletion_reads_as_a_deletion(self, caplog):
        processor = _group_processor([_variable()])

        diff = _diff(processor, "group_variables", {"one": {"key": "TEST_VARIABLE_1", "delete": True}}, caplog)

        assert "TEST_VARIABLE_1@*" in diff
        assert "(will be deleted)" in diff

    def test_project_variable_gitlab_has_not_got_says_the_section_will_fail(self, caplog):
        processor = _project_processor([_variable()])

        diff = _diff(processor, "variables", {"one": {"key": "OTHER_VARIABLE", "delete": True}}, caplog)

        assert "OTHER_VARIABLE@*" in diff
        assert "(not in GitLab - deleting it will fail this section)" in diff
        assert "(will be deleted)" not in diff

    def test_group_variable_gitlab_has_not_got_says_the_section_will_fail(self, caplog):
        processor = _group_processor([_variable()])

        diff = _diff(processor, "group_variables", {"one": {"key": "OTHER_VARIABLE", "delete": True}}, caplog)

        assert "OTHER_VARIABLE@*" in diff
        assert "(not in GitLab - deleting it will fail this section)" in diff
        assert "(will be deleted)" not in diff

    def test_the_same_key_on_another_scope_is_another_variable(self, caplog):
        processor = _project_processor([_variable()])

        diff = _diff(
            processor,
            "variables",
            {"one": {"key": "TEST_VARIABLE_1", "environment_scope": "prod", "delete": True}},
            caplog,
        )

        assert "TEST_VARIABLE_1@prod" in diff
        assert "(not in GitLab - deleting it will fail this section)" in diff

    def test_a_variable_the_config_applies_is_untouched_by_the_marker(self, caplog):
        processor = _project_processor([_variable()])

        diff = _diff(processor, "variables", {"one": {"key": "TEST_VARIABLE_1", "value": "CHANGED"}}, caplog)

        assert "TEST_VARIABLE_1@*" in diff
        assert "(will be deleted)" not in diff
