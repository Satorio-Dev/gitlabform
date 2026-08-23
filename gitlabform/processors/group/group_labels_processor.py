from logging import info
from typing import Dict, List


from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.labels_processor import LabelsProcessor

from gitlab.v4.objects import Group


class GroupLabelsProcessor(AbstractProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__("group_labels", gitlab)
        self._labels_processor = LabelsProcessor()

    diff_keys_are_entities = True

    def _get_current_state(self, group_path_and_name: str) -> Dict[str, Dict]:
        group: Group = self.gl.get_group_by_path_cached(group_path_and_name)
        return self._labels_processor.get_current_labels_for_diff(group)

    def _get_desired_state(self, entity_config: Dict) -> Dict[str, Dict]:
        return self._labels_processor.get_desired_labels_for_diff(entity_config)

    def _process_configuration(self, group_path_and_name: str, configuration: Dict):
        configured_labels = configuration.get("group_labels", {})

        enforce = configuration.get("group_labels|enforce", False)

        # Remove 'enforce' key from the config so that it's not treated as a "label"
        if enforce:
            configured_labels.pop("enforce")

        group: Group = self.gl.get_group_by_path_cached(group_path_and_name)

        self._labels_processor.process_labels(configured_labels, enforce, group, self._needs_update)
