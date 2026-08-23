from unittest.mock import MagicMock, patch

from gitlabform.processors.group.group_labels_processor import GroupLabelsProcessor
from gitlabform.processors.project.project_labels_processor import ProjectLabelsProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger


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
