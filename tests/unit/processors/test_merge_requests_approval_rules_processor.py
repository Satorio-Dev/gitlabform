from unittest.mock import MagicMock, patch

import pytest

from gitlabform.constants import EXIT_INVALID_INPUT
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

    def test_no_update_when_protected_branch_ids_match(self):
        gitlab_rule = self._gitlab_rule(
            protected_branches=[
                {"id": 231211600, "name": "main"},
                {"id": 231211601, "name": "release/*"},
            ],
        )
        config = {
            "name": "standard",
            "approvals_required": 1,
            "protected_branch_ids": [231211601, 231211600],
        }

        assert self.processor._needs_update(gitlab_rule, config) is False

    def test_update_when_protected_branch_ids_differ(self):
        gitlab_rule = self._gitlab_rule(protected_branches=[{"id": 231211600, "name": "main"}])
        config = {
            "name": "standard",
            "approvals_required": 1,
            "protected_branch_ids": [231211601],
        }

        assert self.processor._needs_update(gitlab_rule, config) is True

    def test_update_when_config_clears_branches_but_gitlab_has_them(self):
        gitlab_rule = self._gitlab_rule(protected_branches=[{"id": 231211600, "name": "main"}])
        config = {"name": "standard", "approvals_required": 1}

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

    def _diff(self, config: dict, caplog) -> str:
        with caplog.at_level("INFO"):
            self.processor._print_diff("foo/bar", config, diff_only_changed=True)
        return "\n".join(r.message for r in caplog.records if "merge_requests_approval_rules changes" in r.message)

    @staticmethod
    def _gitlab_rule(approvals_required=1, users=None, name="security", rule_type="regular"):
        return {
            "id": 1,
            "name": name,
            "rule_type": rule_type,
            "report_type": None,
            "eligible_approvers": [{"id": 5, "username": "jdoe"}],
            "approvals_required": approvals_required,
            "users": users or [{"id": 5, "username": "jdoe"}],
            "groups": [],
            "contains_hidden_groups": False,
            "protected_branches": [{"id": 1, "name": "main"}],
            "applies_to_all_protected_branches": False,
        }

    @staticmethod
    def _config(**overrides):
        rule = {
            "name": "security",
            "approvals_required": 1,
            "user_ids": [5],
            "protected_branches": ["main"],
        }
        rule.update(overrides)
        return {"security rule": rule}

    def test__differing_approvals_required_shows_in_diff(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule(approvals_required=1)]

        text = self._diff(self._config(approvals_required=2), caplog)

        assert "security" in text
        assert "2" in text

    def test__matching_state_is_silent_despite_different_shapes(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule()]

        assert self._diff(self._config(applies_to_all_protected_branches=False), caplog) == ""

    def test__key_the_config_does_not_declare_is_not_a_difference(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule()]

        assert self._diff(self._config(), caplog) == ""

    def test__rule_type_declared_and_equal_is_silent(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule(rule_type="regular")]

        assert self._diff(self._config(rule_type="regular"), caplog) == ""

    def test__rule_type_declared_and_different_is_reported(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule(rule_type="regular")]

        text = self._diff(self._config(rule_type="any_approver"), caplog)

        assert "any_approver" in text

    def test__branches_declared_as_ids_and_equal_are_silent(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule()]
        config = self._config(protected_branch_ids=[1])
        del config["security rule"]["protected_branches"]

        assert self._diff(config, caplog) == ""

    def test__branches_declared_as_ids_and_different_are_reported(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule()]
        config = self._config(protected_branch_ids=[2])
        del config["security rule"]["protected_branches"]

        text = self._diff(config, caplog)

        assert "protected_branch_ids" in text
        assert "2" in text

    def test__rule_only_in_gitlab_is_reported_as_removed_by_enforce(self, caplog):
        self.gitlab.get_approval_rules.return_value = [self._gitlab_rule(name="legacy")]
        config = self._config()
        config["enforce"] = True

        text = self._diff(config, caplog)

        assert "legacy" in text
        assert "(will be removed by enforce)" in text


class TestMergeRequestsApprovalRulesAmbiguousBranches:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = MergeRequestsApprovalRules(self.gitlab)

    @staticmethod
    def _both_ways():
        return {
            "enforce": True,
            "release": {
                "name": "Release Approve",
                "approvals_required": 1,
                "protected_branches": ["main"],
                "protected_branch_ids": [231211600],
            },
        }

    @staticmethod
    def _one_way():
        return {
            "enforce": True,
            "release": {
                "name": "Release Approve",
                "approvals_required": 1,
                "protected_branches": ["main"],
            },
        }

    def test__the_diff_stops_on_a_rule_that_declares_branches_both_ways(self):
        with pytest.raises(SystemExit) as exit_info:
            self.processor._get_desired_state(self._both_ways())

        assert exit_info.value.code == EXIT_INVALID_INPUT

    def test__the_apply_path_stops_on_a_rule_that_declares_branches_both_ways(self):
        with pytest.raises(SystemExit) as exit_info:
            self.processor._can_proceed("foo/bar", {"merge_requests_approval_rules": self._both_ways()})

        assert exit_info.value.code == EXIT_INVALID_INPUT

    def test__both_keys_and_the_rule_are_named_in_the_message(self, caplog):
        with caplog.at_level("CRITICAL"), pytest.raises(SystemExit):
            self.processor._get_desired_state(self._both_ways())

        message = "\n".join(record.message for record in caplog.records)
        assert "release" in message
        assert "protected_branches" in message
        assert "protected_branch_ids" in message

    def test__a_rule_that_declares_branches_one_way_proceeds(self):
        assert self.processor._can_proceed("foo/bar", {"merge_requests_approval_rules": self._one_way()}) is True
        assert "Release Approve" in self.processor._get_desired_state(self._one_way())
