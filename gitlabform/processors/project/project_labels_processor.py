from typing import Dict

from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor

from gitlab.v4.objects import Project

from gitlabform.processors.util.labels_processor import LabelsProcessor


class ProjectLabelsProcessor(AbstractProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__("labels", gitlab)
        self._labels_processor = LabelsProcessor()

    diff_keys_are_entities = True

    def _get_current_state(self, project_and_group: str) -> Dict[str, Dict]:
        project: Project = self.gl.get_project_by_path_cached(project_and_group)
        return self._labels_processor.get_current_labels_for_diff(project)

    def _get_desired_state(self, entity_config: Dict) -> Dict[str, Dict]:
        return self._labels_processor.get_desired_labels_for_diff(entity_config)

    def _reconcile_with_apply(self, project_and_group: str, current: Dict, desired: Dict, entity_config) -> Dict:
        return self._labels_processor.drop_labels_an_ancestor_provides(
            current, desired, self.gl.get_project_by_path_cached(project_and_group)
        )

    def _process_configuration(self, project_and_group: str, configuration: Dict):
        configured_labels = configuration.get("labels", {})

        enforce = configuration.get("labels|enforce", False)

        # Remove 'enforce' key from the config so that it's not treated as a "label"
        if enforce:
            configured_labels.pop("enforce")

        project: Project = self.gl.get_project_by_path_cached(project_and_group)

        self._labels_processor.process_labels(configured_labels, enforce, project, self._needs_update)
