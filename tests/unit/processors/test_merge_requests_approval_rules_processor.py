from unittest.mock import MagicMock, patch

from gitlabform.processors.project.merge_requests_approval_rules import MergeRequestsApprovalRules


class TestMergeRequestsApprovalRulesProcessor:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = MergeRequestsApprovalRules(self.gitlab)

    @staticmethod
    def _gitlab_rule(
        name="standard",
        approvals_required=1,
        users=None,
        groups=None,
        protected_branches=None,
        applies_to_all_protected_branches=False,
        rule_type="regular",
    ):
        return {
            "id": 1,
            "name": name,
            "rule_type": rule_type,
            "report_type": None,
            "eligible_approvers": [],
            "approvals_required": approvals_required,
            "users": users or [],
            "groups": groups or [],
            "contains_hidden_groups": False,
            "protected_branches": protected_branches or [],
            "applies_to_all_protected_branches": applies_to_all_protected_branches,
        }

    def test_no_update_when_users_match(self):
        gitlab_rule = self._gitlab_rule(
            users=[{"id": 5, "username": "alice"}, {"id": 7, "username": "bob"}],
        )
        config = {"name": "standard", "approvals_required": 1, "user_ids": [7, 5]}

        assert self.processor._needs_update(gitlab_rule, config) is False

    def test_no_update_when_groups_match(self):
        gitlab_rule = self._gitlab_rule(groups=[{"id": 3, "name": "sec"}])
        config = {"name": "standard", "approvals_required": 1, "group_ids": [3]}

        assert self.processor._needs_update(gitlab_rule, config) is False

    def test_no_update_when_protected_branches_match(self):
        gitlab_rule = self._gitlab_rule(
            protected_branches=[
                {"id": 1, "name": "main"},
                {"id": 2, "name": "release"},
            ],
        )
        config = {
            "name": "standard",
            "approvals_required": 1,
            "protected_branches": ["release", "main"],
        }

        assert self.processor._needs_update(gitlab_rule, config) is False

    def test_no_update_when_config_omits_user_ids_and_gitlab_has_no_users(self):
        gitlab_rule = self._gitlab_rule()
        config = {"name": "standard", "approvals_required": 1}

        assert self.processor._needs_update(gitlab_rule, config) is False

    def test_no_update_when_gitlab_omits_users_groups_protected_branches_keys(self):
        gitlab_rule = {
            "id": 1,
            "name": "standard",
            "rule_type": "regular",
            "approvals_required": 1,
        }
        config = {"name": "standard", "approvals_required": 1}

        assert self.processor._needs_update(gitlab_rule, config) is False

    def test_update_when_user_ids_differ(self):
        gitlab_rule = self._gitlab_rule(users=[{"id": 5, "username": "alice"}])
        config = {"name": "standard", "approvals_required": 1, "user_ids": [9]}

        assert self.processor._needs_update(gitlab_rule, config) is True

    def test_update_when_config_clears_users_but_gitlab_has_users(self):
        gitlab_rule = self._gitlab_rule(users=[{"id": 5, "username": "alice"}])
        config = {"name": "standard", "approvals_required": 1}

        assert self.processor._needs_update(gitlab_rule, config) is True

    def test_update_when_protected_branches_differ(self):
        gitlab_rule = self._gitlab_rule(
            protected_branches=[{"id": 1, "name": "main"}],
        )
        config = {
            "name": "standard",
            "approvals_required": 1,
            "protected_branches": ["release"],
        }

        assert self.processor._needs_update(gitlab_rule, config) is True

    def test_update_when_approvals_required_changes(self):
        gitlab_rule = self._gitlab_rule(approvals_required=1)
        config = {"name": "standard", "approvals_required": 2}

        assert self.processor._needs_update(gitlab_rule, config) is True

    def test_no_update_for_any_approver_rule(self):
        gitlab_rule = self._gitlab_rule(rule_type="any_approver", approvals_required=0)
        config = {
            "name": "standard",
            "approvals_required": 0,
            "rule_type": "any_approver",
        }

        assert self.processor._needs_update(gitlab_rule, config) is False


class TestMergeRequestsApprovalRulesDryRunDiff:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = MergeRequestsApprovalRules(self.gitlab)

    @staticmethod
    def _diff(current: dict, desired: dict) -> str:
        from gitlabform.processors.util.difference_logger import DifferenceLogger

        return DifferenceLogger.log_diff(
            "merge_requests_approval_rules changes", current, desired, only_changed=True, test=True
        )

    @staticmethod
    def _gitlab_rule(approvals_required=1, users=None):
        return {
            "id": 1,
            "name": "security",
            "rule_type": "regular",
            "report_type": None,
            "eligible_approvers": [{"id": 5, "username": "jdoe"}],
            "approvals_required": approvals_required,
            "users": users or [{"id": 5, "username": "jdoe"}],
            "groups": [],
            "contains_hidden_groups": False,
            "protected_branches": [{"id": 1, "name": "main"}],
            "applies_to_all_protected_branches": False,
        }

    def test__differing_approvals_required_shows_in_diff(self):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule(approvals_required=1)]
        config = {
            "security rule": {
                "name": "security",
                "approvals_required": 2,
                "user_ids": [5],
                "protected_branches": ["main"],
                "applies_to_all_protected_branches": False,
            }
        }

        text = self._diff(
            self.processor._get_current_state("foo/bar"),
            self.processor._get_desired_state(config),
        )

        assert "security" in text
        assert "2" in text

    def test__matching_state_is_silent_despite_different_shapes(self):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule()]
        config = {
            "security rule": {
                "name": "security",
                "approvals_required": 1,
                "user_ids": [5],
                "protected_branches": ["main"],
                "applies_to_all_protected_branches": False,
            }
        }

        assert (
            self._diff(
                self.processor._get_current_state("foo/bar"),
                self.processor._get_desired_state(config),
            )
            == ""
        )
