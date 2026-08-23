from logging import debug
from typing import Dict, Any, List, Optional

from gitlab.base import RESTObject, RESTObjectList
from gitlab.v4.objects import Project
from gitlab.v4.objects import ProjectHook

from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.difference_logger import hide


class HooksProcessor(AbstractProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__("hooks", gitlab)

    diff_keys_are_entities = True
    diff_ignores_undeclared_keys = True

    DIFF_IGNORED_KEYS = frozenset({"id", "project_id", "created_at"})

    def _get_current_state(self, project_and_group: str) -> Optional[dict]:
        project: Project = self.gl.get_project_by_path_cached(project_and_group)
        current_state = {}
        for hook in project.hooks.list(get_all=True):
            hook_state = {
                key: value
                for key, value in sorted(hook.asdict().items())
                if key not in self.DIFF_IGNORED_KEYS and value is not None
            }
            current_state[hook_state["url"]] = hook_state
        return current_state

    diff_honours_delete_flag = True

    def _get_desired_state(self, entity_config: dict) -> dict:
        """The configured hooks, keyed by url, with the token and the url_variables
        masked: GET does not return them, so they can never be compared, and their
        values must not reach the log."""
        desired_state: dict = {}
        for url, hook_config in entity_config.items():
            if url == "enforce" or not isinstance(hook_config, dict):
                continue
            desired_hook = {"url": url, **hook_config}
            if "token" in desired_hook:
                desired_hook["token"] = hide(str(desired_hook["token"]))
            if isinstance(desired_hook.get("url_variables"), list):
                desired_hook["url_variables"] = [
                    (
                        {**url_variable, "value": hide(str(url_variable["value"]))}
                        if isinstance(url_variable, dict) and "value" in url_variable
                        else url_variable
                    )
                    for url_variable in desired_hook["url_variables"]
                ]
            desired_state[url] = dict(sorted(desired_hook.items()))
        return desired_state

    def _process_configuration(self, project_and_group: str, configuration: dict):
        debug("Processing hooks...")
        project: Project = self.gl.get_project_by_path_cached(project_and_group)
        project_hooks: list[ProjectHook] = project.hooks.list(get_all=True)

        hooks_in_config: tuple[str, ...] = tuple(x for x in sorted(configuration["hooks"]) if x != "enforce")

        for hook in hooks_in_config:
            hook_in_gitlab: RESTObject | None = next((h for h in project_hooks if h.url == hook), None)
            hook_config = {"url": hook}
            hook_config.update(configuration["hooks"][hook])

            hook_id = hook_in_gitlab.id if hook_in_gitlab else None

            # Process hooks configured for deletion
            if configuration.get("hooks|" + hook + "|delete"):
                if hook_id:
                    debug(f"Deleting hook '{hook}'")
                    project.hooks.delete(hook_id)
                    debug(f"Deleted hook '{hook}'")
                else:
                    debug(f"Not deleting hook '{hook}', because it doesn't exist")
                continue

            # Process new hook creation
            if not hook_id:
                debug(f"Creating hook '{hook}'")
                created_hook: RESTObject = project.hooks.create(hook_config)
                debug(f"Created hook: {created_hook}")
                continue

            # Processing existing hook updates
            gl_hook: dict = hook_in_gitlab.asdict() if hook_in_gitlab else {}
            if self._needs_update(gl_hook, hook_config):
                debug(f"The hook '{hook}' config is different from what's in gitlab OR it contains a token")
                debug(f"Updating hook '{hook}'")
                updated_hook: Dict[str, Any] = project.hooks.update(hook_id, hook_config)
                debug(f"Updated hook: {updated_hook}")
            else:
                debug(f"Hook '{hook}' remains unchanged")

        # Process hook config enforcements
        if configuration.get("hooks|enforce"):
            for gh in project_hooks:
                if gh.url not in hooks_in_config:
                    debug(
                        f"Deleting hook '{gh.url}' currently setup in the project but it is not in the configuration and enforce is enabled"
                    )
                    project.hooks.delete(gh.id)
