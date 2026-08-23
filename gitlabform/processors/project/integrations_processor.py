from logging import info
from typing import Any

from gitlab.exceptions import GitlabDeleteError
from gitlab.v4.objects import Project, ProjectIntegration
from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.difference_logger import hide


class IntegrationsProcessor(AbstractProcessor):
    SECRET_KEY_MARKERS = ("token", "password", "secret", "webhook", "api_key")

    def __init__(self, gitlab: GitLab):
        super().__init__("integrations", gitlab)

    diff_keys_are_entities = True
    diff_honours_delete_flag = True

    def _get_current_state(self, project_and_group: str) -> dict:
        """The active integrations, keyed by slug, with the password-type properties
        hidden: GitLab does not return their values, so they can never be compared and
        must not reach the log either."""
        project: Project = self.gl.get_project_by_path_cached(project_and_group)
        current_state = {}
        for integration in project.integrations.list(get_all=True):
            if not integration.active:
                continue
            properties = project.integrations.get(integration.slug).asdict().get("properties") or {}
            current_state[integration.slug] = {
                key: self._mask_if_secret(key, value) for key, value in sorted(properties.items()) if value is not None
            }
        return current_state

    def _get_desired_state(self, entity_config: dict) -> dict:
        return {
            slug: {key: self._mask_if_secret(key, value) for key, value in sorted(integration_config.items())}
            for slug, integration_config in entity_config.items()
            if isinstance(integration_config, dict)
        }

    @classmethod
    def _mask_if_secret(cls, key: str, value: Any) -> Any:
        if any(marker in key.lower() for marker in cls.SECRET_KEY_MARKERS):
            return hide(str(value))
        return value

    def _process_configuration(self, project_and_group: str, configuration: dict):
        configured_integrations = configuration.get("integrations", {})
        project: Project = self.gl.get_project_by_path_cached(project_and_group)

        for integration in sorted(configured_integrations):
            gl_integration: ProjectIntegration = project.integrations.get(integration, lazy=True)

            if configured_integrations[integration].get("delete"):
                info(f"Deleting integration: {integration}")
                try:
                    gl_integration.delete()
                except GitlabDeleteError as e:
                    # If we get a 404 the integration does not exist, so we can ignore the error
                    if e.response_code == 404:
                        info(f"Integration {integration} does not exist, skipping deletion.")
                    else:
                        info(f"Failed to delete integration {integration}: {e}")
                        raise
            else:
                info(f"Setting integration: {integration}")
                project.integrations.update(integration, configured_integrations[integration])
