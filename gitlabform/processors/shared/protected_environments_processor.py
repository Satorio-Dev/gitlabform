from logging import error, warning
from typing import Any, Callable, Optional

from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import Key, And
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class ProtectedEnvironmentsNotWritten(Exception):
    pass


class ProtectedEnvironmentsProcessor(MultipleEntitiesProcessor):
    """https://docs.gitlab.com/ee/api/protected_environments.html#protect-repository-environments"""

    def __init__(self, gitlab: GitLab):
        super().__init__(
            "protected_environments",
            gitlab,
            list_method_name=gitlab.list_protected_environments,
            add_method_name=self._protect_and_read_back,
            delete_method_name=gitlab.unprotect_environment,
            defining=Key("name"),
            required_to_create_or_update=And(Key("name"), Key("deploy_access_levels")),
        )

        self.protect_method: Callable = gitlab.protect_a_repository_environment
        self.custom_diff_analyzers["deploy_access_levels"] = self.recursive_diff_analyzer
        self._not_written: dict[str, list[str]] = {}

    KEYS_NOT_SENT_TO_GITLAB: frozenset = frozenset({"delete"})

    def _process_configuration(self, project_and_group: str, configuration: dict):
        self._not_written = {}

        super()._process_configuration(project_and_group, configuration)

        if self._not_written:
            raise ProtectedEnvironmentsNotWritten(
                f"GitLab accepted the protected environments write in {project_and_group}"
                f" and did not store all of it: "
                + "; ".join(
                    f"'{name}' is missing {', '.join(lost)}" for name, lost in sorted(self._not_written.items())
                )
            )

    def _protect_and_read_back(self, project_and_group: str, entity_config: dict) -> None:
        """Write the environment, then read it back and say what GitLab kept.

        A 201 is not evidence that the write landed. GitLab answers 201 to a write it
        stores only in part - an approval rule naming a user who is not allowed to
        approve is dropped without a word - so the answer to the write is checked
        against the state the next reader will see, not against itself.
        """
        self.protect_method(project_and_group, entity_config)

        name = entity_config["name"]
        written = self._read_back(project_and_group, name)

        if written is None:
            self._record_not_written(project_and_group, name, ["the environment itself"])
            return

        for key in self._unreported_keys(written, entity_config):
            warning(
                f"GitLab does not report '{key}' of protected environment '{name}'"
                f" in {project_and_group} back, so it was NOT verified."
            )

        lost = self._lost_in_write(written, entity_config)
        if lost:
            self._record_not_written(project_and_group, name, lost)

    def _record_not_written(self, project_and_group: str, name: str, lost: list[str]) -> None:
        error(
            f"GitLab accepted the write of protected environment '{name}' in {project_and_group}"
            f" and did not store: {', '.join(lost)}"
        )
        self._not_written[name] = lost

    def _read_back(self, project_and_group: str, name: str) -> Optional[dict]:
        for environment in self.list_method(project_and_group):
            if isinstance(environment, dict) and environment.get("name") == name:
                return environment
        return None

    @classmethod
    def _unreported_keys(cls, written: dict, wanted: dict) -> list[str]:
        """Keys the config asked for that the read-back holds no answer of either way."""
        return sorted(key for key in wanted if key not in cls.KEYS_NOT_SENT_TO_GITLAB and key not in written)

    @classmethod
    def _lost_in_write(cls, written: dict, wanted: dict) -> list[str]:
        """What the config asked for and the read-back does not hold, named one by one."""
        lost = []

        for key in sorted(wanted):
            if key in cls.KEYS_NOT_SENT_TO_GITLAB or key not in written:
                continue

            asked = wanted[key]
            live = written[key]

            if isinstance(asked, list) and isinstance(live, list):
                for entry in asked:
                    if not any(cls._entries_match(candidate, entry) for candidate in live):
                        lost.append(f"{key} {entry}")
            elif not cls._entries_match(live, asked):
                lost.append(f"{key} {asked} (GitLab has {live})")

        return lost

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
