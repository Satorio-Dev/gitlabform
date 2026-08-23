from typing import Any

from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import Key, And
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class ProtectedEnvironmentsProcessor(MultipleEntitiesProcessor):
    """https://docs.gitlab.com/ee/api/protected_environments.html#protect-repository-environments"""

    def __init__(self, gitlab: GitLab):
        super().__init__(
            "protected_environments",
            gitlab,
            list_method_name=gitlab.list_protected_environments,
            add_method_name=gitlab.protect_a_repository_environment,
            delete_method_name=gitlab.unprotect_environment,
            defining=Key("name"),
            required_to_create_or_update=And(Key("name"), Key("deploy_access_levels")),
        )

        self.custom_diff_analyzers["deploy_access_levels"] = self.recursive_diff_analyzer

    def _get_current_state(self, project_and_group: str) -> dict[str, dict[str, Any]]:
        return {
            environment["name"]: {
                key: (
                    self._trim_access_levels(environment[key])
                    if isinstance(environment[key], list)
                    else environment[key]
                )
                for key in sorted(environment)
            }
            for environment in self.list_method(project_and_group)
        }

    def _get_desired_state(self, entity_config: dict) -> dict[str, dict[str, Any]]:
        return {
            environment["name"]: {
                key: (
                    self._sort_access_levels(environment[key])
                    if isinstance(environment[key], list)
                    else environment[key]
                )
                for key in sorted(environment)
            }
            for alias, environment in entity_config.items()
            if alias != "enforce" and isinstance(environment, dict)
        }

    @staticmethod
    def _trim_access_levels(access_levels: list) -> list:
        return [
            (
                {k: level[k] for k in sorted(level) if k != "id" and level[k] is not None}
                if isinstance(level, dict)
                else level
            )
            for level in access_levels
        ]

    @staticmethod
    def _sort_access_levels(access_levels: list) -> list:
        return [dict(sorted(level.items())) if isinstance(level, dict) else level for level in access_levels]
