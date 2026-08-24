from logging import error, warning
from typing import Any, Callable, Optional

from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import Key, And
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor
from gitlabform.processors.util.entity_matching import pair_entries


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
            edit_method_name=self._update_and_read_back,
        )

        self.protect_method: Callable = gitlab.protect_a_repository_environment
        self.update_method: Callable = gitlab.update_a_repository_environment
        self.custom_diff_analyzers["deploy_access_levels"] = self.recursive_diff_analyzer
        self.custom_diff_analyzers["approval_rules"] = self.recursive_diff_analyzer
        self._not_written: dict[str, list[str]] = {}

    KEYS_NOT_SENT_TO_GITLAB: frozenset = frozenset({"delete"})
    IDENTITY_KEYS: frozenset = frozenset({"name"})
    KEYS_UPDATABLE_IN_PLACE: frozenset = frozenset({"deploy_access_levels", "approval_rules"})

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
        self._read_back_and_report(project_and_group, entity_config)

    def _update_and_read_back(self, project_and_group: str, entity_in_gitlab: dict, entity_config: dict) -> None:
        """Change the environment where it stands, then read it back and say what GitLab kept.

        Updating by deleting the environment and protecting it anew leaves it unprotected
        between the two requests - anyone allowed to deploy to an unprotected environment
        is allowed to deploy to this one, for as long as the second request takes, and for
        good if the run dies in between. GitLab's update endpoint changes the access levels
        where they stand, so that window only opens for a change the endpoint cannot carry,
        and it says so when it does.
        """
        name = entity_config["name"]
        beyond_the_update_endpoint = self._keys_not_updatable_in_place(entity_in_gitlab, entity_config)

        if beyond_the_update_endpoint:
            warning(
                f"Protected environment '{name}' in {project_and_group} is deleted and protected anew"
                f" rather than updated where it stands, because GitLab's update endpoint does not carry"
                f" {', '.join(beyond_the_update_endpoint)}."
                f" The environment is unprotected until the second request lands."
            )
            self.delete_method(project_and_group, entity_in_gitlab)
            self.protect_method(project_and_group, entity_config)
        else:
            for request in self._update_requests(self._update_payload(entity_in_gitlab, entity_config)):
                self.update_method(project_and_group, name, request)

        self._read_back_and_report(project_and_group, entity_config)

    def _keys_not_updatable_in_place(self, entity_in_gitlab: dict, entity_config: dict) -> list[str]:
        """The keys the config asks to change that GitLab's update endpoint does not take."""
        return sorted(
            key
            for key, wanted in entity_config.items()
            if key not in self.KEYS_NOT_SENT_TO_GITLAB
            and key not in self.IDENTITY_KEYS
            and key not in self.KEYS_UPDATABLE_IN_PLACE
            and not self._entries_match(entity_in_gitlab.get(key), wanted)
        )

    def _update_payload(self, entity_in_gitlab: dict, entity_config: dict) -> dict:
        payload: dict[str, Any] = {}

        for key, wanted in entity_config.items():
            if key in self.KEYS_NOT_SENT_TO_GITLAB or key in self.IDENTITY_KEYS:
                continue

            live = entity_in_gitlab.get(key)
            if key in self.KEYS_UPDATABLE_IN_PLACE and isinstance(wanted, list) and isinstance(live, list):
                changes = self._entry_changes(key, live, wanted)
                if changes:
                    payload[key] = changes
            else:
                payload[key] = wanted

        return payload

    @classmethod
    def _update_requests(cls, payload: dict) -> list[dict]:
        """The payload as the requests GitLab takes, in the order it takes them.

        GitLab reads every entry of such a list as one to create and validates it as one,
        the entries carrying "_destroy" among them, and answers 400 naming a field a
        deletion has no reason to hold. The same deletions sent by themselves are
        accepted, so a payload that both creates and destroys goes as two requests - the
        deletions first, so that a rule the config replaces is gone before its
        replacement arrives and the endpoint never holds both at once. A payload that
        only creates, or only destroys, goes as it stands, in one request.
        """
        destroying: dict[str, Any] = {}
        remaining: dict[str, Any] = {}
        creates = False

        for key, value in payload.items():
            if key not in cls.KEYS_UPDATABLE_IN_PLACE or not isinstance(value, list):
                remaining[key] = value
                continue

            destroyed = [entry for entry in value if cls._destroys(entry)]
            kept = [entry for entry in value if not cls._destroys(entry)]

            if destroyed:
                destroying[key] = destroyed
            if kept:
                remaining[key] = kept
                creates = True

        if not destroying or not creates:
            return [payload]

        return [destroying, remaining]

    @staticmethod
    def _destroys(entry: Any) -> bool:
        return isinstance(entry, dict) and bool(entry.get("_destroy"))

    @classmethod
    def _entry_changes(cls, key: str, entries_in_gitlab: list, entries_in_config: list) -> list:
        """The entries to send so that GitLab ends up holding what the config asks for.

        An entry of these lists is created when it comes without an id, and deleted when
        it comes with an id and "_destroy". So an entry that already has a counterpart in
        GitLab is left out of the request entirely, an entry that has none is sent to be
        created, and a counterpart that no entry claims is sent to be deleted. How many
        requests these go in is _update_requests' to answer.
        """
        paired = pair_entries(entries_in_gitlab, entries_in_config, cls._entries_match)
        claimed = set(paired.values())

        changes = [entry for index, entry in enumerate(entries_in_config) if index not in paired]

        for index, entry in enumerate(entries_in_gitlab):
            if index in claimed:
                continue
            if not isinstance(entry, dict) or "id" not in entry:
                warning(
                    f"An entry of '{key}' that GitLab reports without an id cannot be deleted"
                    f" by an update and stays: {entry}"
                )
                continue

            changes.append({"id": entry["id"], "_destroy": True})

        return changes

    def _read_back_and_report(self, project_and_group: str, entity_config: dict) -> None:
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
