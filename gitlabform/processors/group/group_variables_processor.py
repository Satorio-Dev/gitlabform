from typing import Any, Dict
from logging import info

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import Group

from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.difference_logger import hide, TO_BE_DELETED
from gitlabform.processors.util.variables_processor import VariablesProcessor


class GroupVariablesProcessor(AbstractProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__("group_variables", gitlab)
        self._variables_processor = VariablesProcessor(self._needs_update)

    def _process_configuration(self, project_and_group: str, configuration: Dict[str, Any]) -> None:
        group: Group = self.gl.get_group_by_path_cached(project_and_group)

        configured_variables = configuration.get("group_variables", {})
        enforce_mode: bool = configured_variables.get("enforce", False)

        if enforce_mode:
            info(f"Enforce mode enabled for variables in {project_and_group}")
            # Remove 'enforce' key from the config so that it's not treated as a variable
            configured_variables.pop("enforce")

        self._variables_processor.process_variables(group, configured_variables, enforce_mode)

    diff_keys_are_entities = True
    diff_honours_delete_flag = True
    diff_delete_of_absent_entity_is_noop = False

    def _diff_delete_marker(self, identity: str, wanted: dict, current: dict) -> str:
        if identity in current:
            return TO_BE_DELETED
        return VariablesProcessor.DELETE_OF_ABSENT_VARIABLE

    def _get_current_state(self, project_and_group: str) -> Dict[str, Dict[str, Any]]:
        try:
            group: Group = self.gl.get_group_by_path_cached(project_and_group)
            variables = self._variables_processor.get_variables_from_gitlab(group)
        except GitlabGetError:
            variables = []

        return {self._variable_identity(v.asdict()): self._masked_variable(v.asdict()) for v in variables}

    def _get_desired_state(self, entity_config: dict) -> Dict[str, Dict[str, Any]]:
        return {
            self._variable_identity(var): self._masked_variable(var)
            for alias, var in entity_config.items()
            if alias != "enforce" and isinstance(var, dict)
        }

    @staticmethod
    def _variable_identity(var: Dict[str, Any]) -> str:
        """Compose a stable diff key. GitLab allows the same variable key on multiple
        environment scopes, so `key` alone is not unique; `key@scope` is."""
        return f"{var.get('key')}@{var.get('environment_scope', '*')}"

    @staticmethod
    def _masked_variable(var: Dict[str, Any]) -> Dict[str, Any]:
        masked = {k: var[k] for k in sorted(var) if k not in {"id", "_links"}}
        if "value" in masked:
            masked["value"] = hide(str(masked["value"]))
        return masked
