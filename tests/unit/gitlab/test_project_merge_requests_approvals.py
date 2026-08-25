from gitlabform.gitlab.project_merge_requests_approvals import (
    GitLabProjectMergeRequestsApprovals,
)


class FakeApprovalsApi(GitLabProjectMergeRequestsApprovals):
    """The approval rules API with the two calls that leave the process replaced.

    `_get_project_id` and `_get_protected_branch_id` are the only questions this class
    asks GitLab besides the write itself, and both are lookups. Answering them from a
    dict leaves every line that composes the request exactly where it is.
    """

    BRANCH_IDS = {"main": 231211600, "release/*": 231211601}

    def __init__(self):
        self.sent = []

    def _get_project_id(self, project_and_group_name):
        return "42"

    def _get_protected_branch_id(self, project_and_group_name, branch):
        return self.BRANCH_IDS[branch]

    def _make_requests_to_api(
        self,
        path_as_format_string,
        args=None,
        method="GET",
        data=None,
        expected_codes=200,
        json=None,
    ):
        self.sent.append({"path": path_as_format_string, "method": method, "json": json})
        return {}

    @property
    def last_json(self):
        return self.sent[-1]["json"]


class TestEditApprovalRuleBranches:
    def setup_method(self):
        self.api = FakeApprovalsApi()

    def test__branch_names_are_resolved_to_ids(self):
        self.api.edit_approval_rule(
            "group/project",
            {"id": 7},
            {"name": "Release Approve", "approvals_required": 1, "protected_branches": ["main"]},
        )

        assert self.api.last_json["protected_branch_ids"] == [231211600]
        assert "protected_branches" not in self.api.last_json

    def test__wildcard_branch_names_are_resolved_to_ids(self):
        self.api.edit_approval_rule(
            "group/project",
            {"id": 7},
            {"name": "Minimum Required Approvals", "approvals_required": 1, "protected_branches": ["release/*"]},
        )

        assert self.api.last_json["protected_branch_ids"] == [231211601]

    def test__branch_ids_the_config_declares_are_sent_as_they_stand(self):
        self.api.edit_approval_rule(
            "group/project",
            {"id": 7},
            {"name": "Release Approve", "approvals_required": 1, "protected_branch_ids": [231211600]},
        )

        assert self.api.last_json["protected_branch_ids"] == [231211600]

    def test__a_rule_that_names_no_branches_at_all_clears_them(self):
        self.api.edit_approval_rule(
            "group/project",
            {"id": 7},
            {"name": "Release Approve", "approvals_required": 1},
        )

        assert self.api.last_json["protected_branch_ids"] == []

    def test__a_rule_that_names_no_approvers_clears_them(self):
        self.api.edit_approval_rule(
            "group/project",
            {"id": 7},
            {"name": "Release Approve", "approvals_required": 1},
        )

        assert self.api.last_json["user_ids"] == []
        assert self.api.last_json["group_ids"] == []

    def test__declared_approvers_are_sent_as_they_stand(self):
        self.api.edit_approval_rule(
            "group/project",
            {"id": 7},
            {"name": "Release Approve", "approvals_required": 1, "user_ids": [5], "group_ids": [107572970]},
        )

        assert self.api.last_json["user_ids"] == [5]
        assert self.api.last_json["group_ids"] == [107572970]


class TestAddApprovalRuleBranches:
    def setup_method(self):
        self.api = FakeApprovalsApi()

    def test__branch_names_are_resolved_to_ids(self):
        self.api.add_approval_rule(
            "group/project",
            {"name": "Release Approve", "approvals_required": 1, "protected_branches": ["main"]},
        )

        assert self.api.last_json["protected_branch_ids"] == [231211600]
        assert "protected_branches" not in self.api.last_json

    def test__branch_ids_the_config_declares_are_sent_as_they_stand(self):
        self.api.add_approval_rule(
            "group/project",
            {"name": "Release Approve", "approvals_required": 1, "protected_branch_ids": [231211600]},
        )

        assert self.api.last_json["protected_branch_ids"] == [231211600]

    def test__a_rule_that_names_no_branches_stays_without_them(self):
        self.api.add_approval_rule(
            "group/project",
            {"name": "All Members", "approvals_required": 0, "rule_type": "any_approver"},
        )

        assert "protected_branch_ids" not in self.api.last_json
