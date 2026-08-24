from abc import ABC, abstractmethod
from logging import debug
from typing import Any, Callable, Optional, Union

import requests
from logging import info

from gitlabform.gitlab import GitLab, PythonGitlab
from gitlabform.gitlab import GitlabWrapper
from gitlabform.output import EffectiveConfigurationFile
from gitlabform.processors.util.decorators import configuration_to_safe_dict
from gitlabform.processors.util.difference_logger import (
    DifferenceLogger,
    NOTHING_TO_DELETE,
    ONLY_IN_GITLAB,
    REMOVED_BY_ENFORCE,
    TO_BE_DELETED,
)


class AbstractProcessor(ABC):
    def __init__(self, configuration_name: str, gitlab: GitLab):
        self.configuration_name = configuration_name
        self.gitlab = gitlab
        self.custom_diff_analyzers: dict[
            str,
            Callable[[str, list[dict[str, Union[str, int]]], list[dict[str, int]]], bool],
        ] = {}
        self.gl: PythonGitlab = GitlabWrapper(self.gitlab).get_gitlab()

    @configuration_to_safe_dict
    def process(
        self,
        project_or_project_and_group: str,
        configuration,
        dry_run: bool,
        diff_only_changed: bool,
        effective_configuration: EffectiveConfigurationFile,
    ):
        if self._section_is_in_config(configuration):
            if configuration.get(f"{self.configuration_name}|skip"):
                info(f"Skipping section '{self.configuration_name}' - explicitly configured to do so.")
                return
            elif configuration.get("project|archive") and self.configuration_name != "project":
                info(f"Skipping section '{self.configuration_name}' - it is configured to be archived.")
                return

            if dry_run:
                info(f"Processing section '{self.configuration_name}' in dry-run mode.")
                project_transfer_source = ""
                try:
                    project_transfer_source = configuration["project"]["transfer_from"]
                    info(f"""Project {project_or_project_and_group} is configured to be transferred, 
                        diffing config from transfer source project {project_transfer_source}.""")
                except (KeyError, TypeError):
                    pass

                declared = configuration.get(self.configuration_name)
                self._print_diff(
                    project_transfer_source or project_or_project_and_group,
                    {} if declared is None else declared,
                    diff_only_changed=diff_only_changed,
                )
            else:
                info(f"Processing section '{self.configuration_name}'")
                if self._can_proceed(project_or_project_and_group, configuration):
                    self._process_configuration_with_retries(project_or_project_and_group, configuration)

            effective_configuration.add_configuration(
                project_or_project_and_group,
                self.configuration_name,
                configuration.get(self.configuration_name),
            )
        else:
            info(f"Skipping section '{self.configuration_name}' - not in config.")

    def _section_is_in_config(self, configuration: dict):
        return self.configuration_name in configuration

    def _process_configuration_with_retries(self, project_or_project_and_group: str, configuration: dict):
        retry = 1
        max_retries = 3

        while True:
            try:
                if retry > 1:
                    info(f"Retrying section '{self.configuration_name}' - {retry}/{max_retries}...")

                self._process_configuration(
                    project_or_project_and_group,
                    configuration,
                )

                return
            except Exception as e:
                if retry > max_retries:
                    raise MaxProcessorRetriesExceeded from e

                if self._should_retry_processor(e):
                    retry += 1
                    continue
                else:
                    raise e

    @staticmethod
    def _should_retry_processor(e: Exception) -> bool:
        # Most possible failures during processing are handled by the HTTP request retries in GitLabCore class,
        # but in some cases we cannot do that on that level.

        # If we already retried on a request level, don't retry again
        if "Max retries exceeded with url" in str(e):
            return False

        # One case is when a POST request is made and the request is sent, but we got no (or incomplete?) response.
        # Because we don't know if the particular POST request was done under the hood (f.e. an entity was created),
        # we cannot retry just the single request (f.e. if it was created then a retry would either create a duplicate
        # of the entity or fail with an error, if duplicates are not allowed in a given case).

        # Then we need to retry the whole section (f.e. files) for a given entity (f.e. project foo/bar), so the checks
        # for the initial state will re-run (f.e. checking if that entity already exists or not).

        # fmt: off
        if type(e) == requests.exceptions.ConnectionError \
                and "RemoteDisconnected('Remote end closed connection without response')" in str(e):
            return True
        # fmt: on

        return False

    @abstractmethod
    def _process_configuration(self, project_or_project_and_group: str, configuration: dict):
        pass

    diff_keys_are_entities: bool = False
    diff_ignores_undeclared_keys: bool = False
    diff_honours_delete_flag: bool = False
    diff_delete_of_absent_entity_is_noop: bool = True

    @staticmethod
    def _keep_only_declared_keys(current: dict, desired: dict) -> dict:
        """Drop from each entity of the current state the keys its counterpart in the
        desired state does not declare. Entities the config does not mention are left
        whole - the removal side of the diff reports them in full."""
        comparable = {}
        for identity, state in current.items():
            wanted = desired.get(identity)
            if isinstance(state, dict) and isinstance(wanted, dict):
                comparable[identity] = {key: value for key, value in state.items() if key in wanted}
            else:
                comparable[identity] = state
        return comparable

    def _diff_removed_marker(self, entity_config) -> Optional[str]:
        """What to show for an entity that is in GitLab and not in the config, or None
        to keep that side of the diff off for this section."""
        if not self.diff_keys_are_entities:
            return None
        enforce = isinstance(entity_config, dict) and bool(entity_config.get("enforce", False))
        return REMOVED_BY_ENFORCE if enforce else ONLY_IN_GITLAB

    def _diff_delete_marker(self, identity: str, wanted: dict, current: dict) -> Optional[str]:
        """What to show instead of the wanted state of an entity the config marks
        "delete: true", or None to leave that entry as it is. Override where the apply
        path has more to say than "removed it" or "it was not there".
        """
        if identity in current:
            return TO_BE_DELETED
        return NOTHING_TO_DELETE if self.diff_delete_of_absent_entity_is_noop else None

    def _mark_entities_to_be_deleted(self, current: dict, desired: dict) -> dict:
        marked = {}
        for identity, wanted in desired.items():
            marker = (
                self._diff_delete_marker(identity, wanted, current)
                if isinstance(wanted, dict) and wanted.get("delete")
                else None
            )
            marked[identity] = wanted if marker is None else marker
        return marked

    def _reconcile_with_apply(
        self, project_or_project_and_group: str, current: dict, desired: dict, entity_config
    ) -> dict:
        """Last word on the config side of the diff, with both sides in hand.

        Override wherever the apply path skips an entity for a reason only that path can
        see - a directive elsewhere in the config, or a state of GitLab that
        _get_desired_state() is never handed. The default changes nothing.
        """
        return desired

    def _get_current_state(self, project_or_project_and_group: str) -> Optional[dict]:
        """Fetch the current state from GitLab for the centralized dry-run diff.

        Override in subclasses to enable diffing for their section. Return None (the
        default) to opt out.
        """
        return None

    def _get_desired_state(self, entity_config: dict) -> dict:
        """Return the config side of the diff. Override only when the config needs
        slicing or normalizing so its keys line up with the current state.
        """
        return entity_config

    def _print_diff(self, project_or_project_and_group: str, entity_config, diff_only_changed: bool):
        current = self._get_current_state(project_or_project_and_group)
        if current is None:
            debug(f"Diffing for section '{self.configuration_name}' is not supported yet")
            return

        desired = self._get_desired_state(entity_config)
        if self.diff_honours_delete_flag:
            desired = self._mark_entities_to_be_deleted(current, desired)
        desired = self._reconcile_with_apply(project_or_project_and_group, current, desired, entity_config)
        if self.diff_ignores_undeclared_keys:
            current = self._keep_only_declared_keys(current, desired)

        DifferenceLogger.log_diff(
            f"{self.configuration_name} changes",
            current,
            desired,
            only_changed=diff_only_changed,
            removed_marker=self._diff_removed_marker(entity_config),
        )

    def _needs_update(
        self,
        entity_in_gitlab: dict,
        entity_in_configuration: dict,
    ):
        # in the configuration we often don't define every key value because we rely on the defaults.
        # that's why GitLab API often returns many more keys than we have in the configuration.

        # so to decide if the entity should be updated:
        # a) we look for ANY settings that are ONLY in configuration,
        # a) we compare the settings that are in both configuration and gitlab,

        keys_only_in_configuration = set(entity_in_configuration.keys()) - set(entity_in_gitlab.keys())
        if len(keys_only_in_configuration) > 0:
            return True

        keys_on_both_sides = set(entity_in_configuration.keys()) & set(entity_in_gitlab.keys())
        for key in keys_on_both_sides:
            if key in self.custom_diff_analyzers:
                if self.custom_diff_analyzers[key](key, entity_in_gitlab[key], entity_in_configuration[key]):
                    debug(f"the custom diff analyzer of [{key}] reports a difference")
                    return True

                continue

            if entity_in_gitlab[key] != entity_in_configuration[key]:
                debug(
                    f"entity_in_gitlab[{key}] -> {entity_in_gitlab[key]} != entity_in_configuration[{key}] -> {entity_in_configuration[key]}"
                )
                return True

        return False

    @staticmethod
    def recursive_diff_analyzer(cfg_key: str, cfg_in_gitlab: list, local_cfg: list) -> bool:
        """
        :return: True if the lists hold a different set of entries, False otherwise.

        The order GitLab returns the entries in is not the order they are declared in,
        so an entry is compared against whichever counterpart it matches, not against
        the one that happens to share its index.
        """
        if len(cfg_in_gitlab) != len(local_cfg):
            return True

        taken: dict[int, int] = {}

        def take(local_index: int, tried: set[int]) -> bool:
            for gitlab_index in range(len(cfg_in_gitlab)):
                if gitlab_index in tried:
                    continue
                if not AbstractProcessor._entries_match(cfg_in_gitlab[gitlab_index], local_cfg[local_index]):
                    continue

                tried.add(gitlab_index)
                if gitlab_index not in taken or take(taken[gitlab_index], tried):
                    taken[gitlab_index] = local_index
                    return True

            return False

        for local_index in range(len(local_cfg)):
            if not take(local_index, set()):
                debug(
                    f"* An entry of [{cfg_key}] has no counterpart in GitLab:"
                    f"\n Local :: {local_cfg[local_index]} not in GitLab :: {cfg_in_gitlab}"
                )
                return True

        return False

    @staticmethod
    def _entries_match(entry_in_gitlab: Any, entry_in_configuration: Any) -> bool:
        """
        :return: True if the two entries agree on every key they both declare.

        An entry the configuration declares only by keys GitLab does not report is a
        different entry, not an entry there is nothing to disagree about.
        """
        if not isinstance(entry_in_gitlab, dict) or not isinstance(entry_in_configuration, dict):
            return bool(entry_in_gitlab == entry_in_configuration)

        from_gitlab = {k: v for k, v in entry_in_gitlab.items() if v is not None}
        keys_on_both_sides = set(from_gitlab.keys()) & set(entry_in_configuration.keys())

        if not keys_on_both_sides:
            return not entry_in_configuration

        for key in keys_on_both_sides:
            if isinstance(from_gitlab[key], list) and isinstance(entry_in_configuration[key], list):
                if AbstractProcessor.recursive_diff_analyzer(key, from_gitlab[key], entry_in_configuration[key]):
                    return False
                continue

            if from_gitlab[key] != entry_in_configuration[key]:
                return False

        return True

    def _can_proceed(self, project_or_group: str, configuration: dict):
        return True


class MaxProcessorRetriesExceeded(Exception):
    pass
