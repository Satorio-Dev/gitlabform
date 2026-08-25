from logging import info, warning
from typing import Dict, List, Callable, Union

from gitlab.v4.objects import Group, Project, ProjectLabel, GroupLabel


class LabelsProcessor:

    DIFF_KEYS = ["name", "color", "description", "priority"]

    def get_current_labels_for_diff(self, group_or_project: Group | Project) -> Dict[str, Dict]:
        """Return the labels created directly on the project/group (the only ones
        managed here), keyed by label name, for the centralized dry-run diff."""
        return {label.name: self._label_for_diff(label.asdict()) for label in self.list_own_labels(group_or_project)}

    def list_own_labels(self, group_or_project: Group | Project) -> List:
        """The labels this project/group owns - the only ones this section may touch.

        Asking for "include_ancestor_groups=false" is not enough: the projects API
        returns the ancestor groups' labels anyway, flagged "is_project_label": false.
        A label whose response carries no such flag is kept, because absence of the
        field means "cannot tell" and the safe side of that is noise rather than a
        silent deletion of somebody else's label.
        """
        return [
            label
            for label in group_or_project.labels.list(get_all=True, include_ancestor_groups=False)
            if not self._belongs_to_an_ancestor(label)
        ]

    @staticmethod
    def _belongs_to_an_ancestor(label) -> bool:
        attributes = label.asdict() if hasattr(label, "asdict") else label
        return attributes.get("is_project_label") is False

    def get_desired_labels_for_diff(self, configured_labels: Dict) -> Dict[str, Dict]:
        return {
            label.get("name", key): self._label_for_diff({"name": key, **label})
            for key, label in configured_labels.items()
            if key != "enforce" and isinstance(label, dict)
        }

    PROVIDED_BY_AN_ANCESTOR = "provided by an ancestor group - will not be created here"

    def drop_labels_an_ancestor_provides(
        self, current: Dict[str, Dict], desired: Dict[str, Dict], group_or_project: Group | Project
    ) -> Dict:
        """Leave out of the diff every configured label that this project/group does not
        own and will not be given, because an ancestor group already has it.

        The apply path says so and creates nothing, so counting one as a change leaves an
        already converged tree announcing the same non-event on every run - 37 of them in
        one live subgroup - and a plan that is never empty is a plan nobody reads. They
        are named once instead, in a line of their own, so that leaving them out of the
        diff is not the same as saying nothing about them.

        Matched by name, which is how both sides of this diff are keyed.
        """
        missing = [name for name in desired if name not in current]
        if not missing:
            return desired

        inherited = {label.name for label in group_or_project.labels.list(get_all=True)}
        provided = sorted(name for name in missing if name in inherited)
        if not provided:
            return desired

        info(
            f"Left out of the diff - {len(provided)} configured label(s) {self.PROVIDED_BY_AN_ANCESTOR}:"
            f" {', '.join(provided)}."
        )
        return {name: wanted for name, wanted in desired.items() if name not in provided}

    def _label_for_diff(self, label: Dict) -> Dict:
        return {k: label[k] for k in self.DIFF_KEYS if label.get(k) is not None}

    # Groups and Projects share the same API for .labels within python-gitlab
    def process_labels(
        self,
        configured_labels: Dict,
        enforce: bool,
        group_or_project: Group | Project,
        needs_update: Callable,  # self._needs_update passed from AbstractProcessor called process_labels
    ):
        # Only get Labels created directly on the project/group
        existing_group_labels = self.list_own_labels(group_or_project)
        existing_group_and_parent_labels = group_or_project.labels.list(get_all=True)
        existing_label_keys: List = []

        if isinstance(group_or_project, Group):
            parent_object_type = "Group"
        else:
            parent_object_type = "Project"

        gitlab_labels_to_delete: List = []

        for label_to_update in existing_group_labels:
            label_name_in_gl = label_to_update.name
            updated_label = False
            info(f"Checking if {label_name_in_gl} is in Configuration to update or delete")

            for key, configured_label in configured_labels.items():
                configured_label_name = configured_label.get("name")
                # Key in YAML may not match the "name" value in Gitlab or YAML, so we must match on both
                if self.configured_label_matches_gitlab_label(configured_label_name, key, label_name_in_gl):
                    # label exists in GL, so update
                    existing_label_keys.append(key)
                    updated_label = True

                    if needs_update(label_to_update.asdict(), configured_label):
                        self.update_existing_label(
                            configured_label,
                            self.get_label(group_or_project, label_to_update),
                            parent_object_type,
                        )
                    else:
                        info(f"No update required for label: {label_name_in_gl}")
                    break

            if not updated_label:
                gitlab_labels_to_delete.append(label_to_update)

        # Delete labels no longer in config
        for label_to_delete in gitlab_labels_to_delete:
            label_name_in_gl = label_to_delete.name

            info(f"{label_name_in_gl} not in configured labels")
            # only delete labels when enforce is true, because user's maybe automatically applying labels based
            # on Repo state, for example: Compliance Framework labels based on language or CI-template status
            if enforce:
                info(f"Removing {label_name_in_gl} from {parent_object_type}")
                self.get_label(group_or_project, label_to_delete).delete()

        # add new labels

        for label_key in configured_labels.keys():
            if label_key not in existing_label_keys:
                info(f"Creating new label with key: {label_key}, on {parent_object_type}")
                self.create_new_label(
                    configured_labels, group_or_project, label_key, parent_object_type, existing_group_and_parent_labels
                )

    @staticmethod
    def configured_label_matches_gitlab_label(configured_label_name: str, key: str, label_name_in_gl: str):
        return (
            configured_label_name is not None and label_name_in_gl == configured_label_name
        ) or label_name_in_gl == key

    @staticmethod
    def get_label(group_or_project, listed_label) -> GroupLabel | ProjectLabel:
        return group_or_project.labels.get(listed_label.id)

    @staticmethod
    def update_existing_label(
        configured_label,
        full_label: GroupLabel | ProjectLabel,
        parent_object_type: str,
    ):
        info(f"Updating {full_label.name} on {parent_object_type}")

        # label APIs in python-gitlab do not supply an update() method
        for key in configured_label:
            full_label.__setattr__(key, configured_label[key])

        full_label.save()

    def create_new_label(
        self,
        configured_labels,
        group_or_project: Group | Project,
        label_key: str,
        parent_object_type: str,
        existing_group_and_parent_labels: Union[List[GroupLabel], List[ProjectLabel]],
    ):
        label = configured_labels.get(label_key)
        configured_label_name = label.get("name")
        found_existing_label = False
        for existing_label in existing_group_and_parent_labels:
            if self.configured_label_matches_gitlab_label(configured_label_name, label_key, existing_label.name):
                warning(
                    f"Label {existing_label.name} already exists either in {group_or_project.name} or on Parent Group, so will not create"
                )
                found_existing_label = True
                break

        if not found_existing_label:
            info(f"Adding label with key: {label_key} to {parent_object_type}")
            group_or_project.labels.create({"name": label_key, **label})
