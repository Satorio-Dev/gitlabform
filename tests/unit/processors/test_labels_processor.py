from unittest.mock import MagicMock, patch

from gitlabform.processors.group.group_labels_processor import GroupLabelsProcessor
from gitlabform.processors.project.project_labels_processor import ProjectLabelsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger, REMOVED_BY_ENFORCE
from gitlabform.processors.util.labels_processor import LabelsProcessor


def _gitlab_label(name="bug", color="#d9534f", description="Bug reported", priority=10):
    """A realistic body of GET /projects/:id/labels or /groups/:id/labels."""
    label = MagicMock()
    label.name = name
    label.asdict.return_value = {
        "id": 1,
        "name": name,
        "color": color,
        "text_color": "#FFFFFF",
        "description": description,
        "description_html": description,
        "open_issues_count": 1,
        "closed_issues_count": 0,
        "open_merge_requests_count": 1,
        "subscribed": False,
        "priority": priority,
        "is_project_label": True,
    }
    return label


def _group_label(name):
    """A label an ancestor group owns, as GET /projects/:id/labels returns it - the
    project endpoint sends it even with include_ancestor_groups=false."""
    label = _gitlab_label(name=name, priority=None)
    label.id = 52332401
    attributes = label.asdict.return_value
    attributes["id"] = 52332401
    attributes["is_project_label"] = False
    attributes.pop("priority", None)
    return label


def _group_api_label(name):
    """A label as GET /groups/:id/labels returns it: no "is_project_label" key at all."""
    label = _gitlab_label(name=name, priority=None)
    attributes = label.asdict.return_value
    attributes.pop("is_project_label", None)
    attributes.pop("priority", None)
    return label


def _label_without_the_flag(name):
    """An older GitLab that does not report "is_project_label" for project labels."""
    label = _gitlab_label(name=name)
    label.asdict.return_value.pop("is_project_label", None)
    return label


def _configured_labels():
    return {
        "enforce": True,
        "bug": {"color": "#d9534f", "description": "Bug reported", "priority": 10},
    }


class TestProjectLabelsDiff:
    def setup_method(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProjectLabelsProcessor(MagicMock())
        self.project = MagicMock()
        self.processor.gl.get_project_by_path_cached.return_value = self.project

    def _diff(self, gitlab_labels, configured_labels):
        self.project.labels.list.return_value = gitlab_labels
        return DifferenceLogger.log_diff(
            "labels changes",
            self.processor._get_current_state("group/project"),
            self.processor._get_desired_state(configured_labels),
            only_changed=True,
            test=True,
        )

    def test_no_diff_when_state_matches(self):
        assert self._diff([_gitlab_label()], _configured_labels()) == ""

    def test_diff_names_the_label_when_color_differs(self):
        diff = self._diff([_gitlab_label(color="#428bca")], _configured_labels())
        assert "bug" in diff
        assert "#428bca" in diff
        assert "#d9534f" in diff

    def test_diff_shows_label_missing_in_gitlab(self):
        diff = self._diff([], _configured_labels())
        assert "bug" in diff
        assert "???" in diff

    def test_current_state_lists_only_direct_labels(self):
        self.project.labels.list.return_value = []
        self.processor._get_current_state("group/project")
        self.project.labels.list.assert_called_once_with(get_all=True, include_ancestor_groups=False)

    def test_desired_state_matches_on_name_key_and_drops_enforce(self):
        desired = self.processor._get_desired_state(
            {"enforce": True, "some yaml key": {"name": "bug", "color": "#d9534f"}}
        )
        assert desired == {"bug": {"name": "bug", "color": "#d9534f"}}


class TestGroupLabelsDiff:
    def setup_method(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = GroupLabelsProcessor(MagicMock())
        self.group = MagicMock()
        self.processor.gl.get_group_by_path_cached.return_value = self.group

    def test_no_diff_when_state_matches(self):
        self.group.labels.list.return_value = [_gitlab_label()]
        diff = DifferenceLogger.log_diff(
            "group_labels changes",
            self.processor._get_current_state("some_group"),
            self.processor._get_desired_state(_configured_labels()),
            only_changed=True,
            test=True,
        )
        assert diff == ""


class TestLabelsFromAncestorGroupsAreNotOurs:
    def setup_method(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProjectLabelsProcessor(MagicMock())
        self.project = MagicMock()
        self.processor.gl.get_project_by_path_cached.return_value = self.project

    def test_an_inherited_label_is_not_in_the_current_state(self):
        self.project.labels.list.return_value = [_gitlab_label(), _group_label("goal::v1-creditron")]

        assert set(self.processor._get_current_state("group/project")) == {"bug"}

    def test_an_inherited_label_is_not_reported_as_removed_by_enforce(self):
        self.project.labels.list.return_value = [_group_label("goal::v1-creditron")]

        diff = DifferenceLogger.log_diff(
            "labels changes",
            self.processor._get_current_state("group/project"),
            self.processor._get_desired_state({"enforce": True}),
            only_changed=True,
            removed_marker=REMOVED_BY_ENFORCE,
            test=True,
        )

        assert diff == ""

    def test_an_inherited_label_never_reaches_the_delete_list(self):
        labels_processor = LabelsProcessor()
        inherited = _group_label("goal::v1-creditron")
        self.project.labels.list.return_value = [inherited]

        labels_processor.process_labels({}, enforce=True, group_or_project=self.project, needs_update=MagicMock())

        self.project.labels.get.assert_not_called()

    def test_a_project_label_the_config_dropped_is_still_deleted(self):
        labels_processor = LabelsProcessor()
        owned = _gitlab_label()
        owned.id = 7
        self.project.labels.list.return_value = [owned]

        labels_processor.process_labels({}, enforce=True, group_or_project=self.project, needs_update=MagicMock())

        self.project.labels.get.assert_called_once_with(7)
        self.project.labels.get.return_value.delete.assert_called_once()

    def test_a_label_without_the_flag_is_kept(self):
        self.project.labels.list.return_value = [_label_without_the_flag("legacy")]

        assert set(self.processor._get_current_state("group/project")) == {"legacy"}


class TestGroupLabelsHaveNoAncestorLeak:
    def setup_method(self):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = GroupLabelsProcessor(MagicMock())
        self.group = MagicMock()
        self.processor.gl.get_group_by_path_cached.return_value = self.group

    def test_a_group_label_body_has_no_flag_and_is_kept(self):
        self.group.labels.list.return_value = [_group_api_label("arch::proposing")]

        assert set(self.processor._get_current_state("some/subgroup")) == {"arch::proposing"}

    def test_the_group_asks_the_api_to_exclude_ancestors(self):
        self.group.labels.list.return_value = []

        self.processor._get_current_state("some/subgroup")

        self.group.labels.list.assert_called_once_with(get_all=True, include_ancestor_groups=False)
