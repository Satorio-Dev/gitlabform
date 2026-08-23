from logging import warning, info
from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor

from gitlab import GitlabGetError, GitlabUpdateError
from gitlab.v4.objects import Project, ProjectResourceGroup


class ResourceGroupsProcessor(AbstractProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__("resource_groups", gitlab)

    diff_keys_are_entities = True

    def _get_current_state(self, project_and_group: str) -> dict:
        project: Project = self.gl.get_project_by_path_cached(project_and_group)
        return {
            resource_group.key: self._comparable_resource_group(resource_group.asdict())
            for resource_group in project.resource_groups.list(get_all=True)
        }

    def _get_desired_state(self, entity_config: dict) -> dict:
        return {name: config for name, config in entity_config.items() if name != "ensure_exists"}

    @staticmethod
    def _comparable_resource_group(resource_group: dict) -> dict:
        return {k: v for k, v in resource_group.items() if k not in {"id", "key", "created_at", "updated_at"}}

    def _process_configuration(self, project_and_group: str, configuration: dict):
        configured_resource_groups: dict = configuration.get("resource_groups", {})
        ensure_exists: bool = configuration.get("resource_groups|ensure_exists", True)

        # Remove 'ensure_exists' from config so that it's not treated as a 'resource group'
        if "ensure_exists" in configured_resource_groups:
            configured_resource_groups.pop("ensure_exists")

        project: Project = self.gl.get_project_by_path_cached(project_and_group)

        for config_resource_group_name in sorted(configured_resource_groups):
            resource_group_in_config = configured_resource_groups[config_resource_group_name]
            try:
                resource_group_in_gitlab: ProjectResourceGroup = project.resource_groups.get(config_resource_group_name)
            except GitlabGetError:
                message = (
                    f"Project is not configured to use resource group: {config_resource_group_name}.\n"
                    f"Add the resource group in your project's .gitlab-ci.yml file.\n"
                    f"For more information, visit https://docs.gitlab.com/ee/ci/resource_groups/#add-a-resource-group.\n"
                    f"Or add 'ensure_exists: false' to gitlabform config to continue processing.\n"
                    f"For more information, visit https://gitlabform.github.io/gitlabform/reference/resource_groups\n"
                )
                if ensure_exists:
                    raise Exception(message)
                else:
                    warning(message)
                    continue

            if self._needs_update(resource_group_in_gitlab.asdict(), resource_group_in_config):
                info(f"Updating resource group '{config_resource_group_name}'")

                try:
                    project.resource_groups.update(resource_group_in_gitlab.key, **resource_group_in_config)
                except GitlabUpdateError as error:
                    warning(f"Resource group update failed. Error: '{error}'")
                    raise GitlabUpdateError
