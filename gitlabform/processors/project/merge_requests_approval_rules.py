import sys
from logging import critical
from typing import Any

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import Key, And
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class MergeRequestsApprovalRules(MultipleEntitiesProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__(
            "merge_requests_approval_rules",
            gitlab,
            list_method_name="get_approval_rules",
            add_method_name="add_approval_rule",
            edit_method_name="edit_approval_rule",
            delete_method_name="delete_approval_rule",
            defining=Key("name"),
            required_to_create_or_update=And(Key("name"), Key("approvals_required")),
        )

    def _needs_update(self, entity_in_gitlab: dict, entity_in_configuration: dict) -> bool:
        return super()._needs_update(
            self._normalize_rule_from_gitlab(entity_in_gitlab),
            self._normalize_rule_from_config(entity_in_configuration),
        )

    SERVER_GENERATED_KEYS = frozenset({"id", "report_type", "eligible_approvers", "contains_hidden_groups"})

    def _get_current_state(self, project_and_group: str) -> dict[str, dict[str, Any]]:
        return {
            rule["name"]: {
                k: v
                for k, v in sorted(self._normalize_rule_from_gitlab(rule).items())
                if k not in self.SERVER_GENERATED_KEYS
            }
            for rule in self.list_method(project_and_group)
        }

    def _get_desired_state(self, entity_config: dict) -> dict[str, dict[str, Any]]:
        self._refuse_branches_declared_both_ways(entity_config)
        return {
            rule["name"]: dict(sorted(self._normalize_rule_from_config(rule).items()))
            for alias, rule in entity_config.items()
            if alias != "enforce" and isinstance(rule, dict)
        }

    def _can_proceed(self, project_or_group: str, configuration: dict) -> bool:
        self._refuse_branches_declared_both_ways(configuration[self.configuration_name])
        return True

    def _refuse_branches_declared_both_ways(self, entity_config: dict) -> None:
        """Stop on a rule that names its branches as names and as ids at once.

        The two keys answer the same question, and nothing makes them answer it the
        same way: `protected_branches: [main]` beside `protected_branch_ids: [7]` is
        two scopings of one rule. The write path resolves the names and would send
        those, so the ids would be dropped without a word - the config would say one
        thing and the project end up with the other.

        Both are named here and neither is applied, on the apply path and in the diff
        alike, so that the run stops where the ambiguity is rather than at whatever it
        would have written.
        """
        declared_both_ways = sorted(
            alias
            for alias, rule in entity_config.items()
            if alias != "enforce"
            and isinstance(rule, dict)
            and "protected_branches" in rule
            and "protected_branch_ids" in rule
        )
        if declared_both_ways:
            critical(
                f"Rule(s) {', '.join(declared_both_ways)} of {self.configuration_name} declare their branches"
                f" both as 'protected_branches' (names) and as 'protected_branch_ids' (ids)."
                f" These are two answers to the same question and only the names would be written."
                f" Please declare the branches of each rule one way or the other."
            )
            sys.exit(EXIT_INVALID_INPUT)

    @staticmethod
    def _normalize_rule_from_gitlab(entity_in_gitlab: dict) -> dict:
        """Read the rule GitLab returns in the shapes the config is written in.

        GitLab answers with users and groups as lists of objects and with the branches
        as objects carrying both a name and an id, while the config (post-transform)
        carries user_ids and group_ids as lists of ints and the branches as either
        names or ids. Without this the base _needs_update reports a difference on
        every run of a rule nothing has changed about.

        The branches are laid out both ways, because the config may speak either, and
        a key the config does not declare costs the comparison nothing.
        """
        gitlab_norm = dict(entity_in_gitlab)
        gitlab_norm["user_ids"] = sorted(u["id"] for u in gitlab_norm.pop("users", []))
        gitlab_norm["group_ids"] = sorted(g["id"] for g in gitlab_norm.pop("groups", []))
        branches_in_gitlab = gitlab_norm.get("protected_branches", [])
        gitlab_norm["protected_branches"] = sorted(b["name"] for b in branches_in_gitlab)
        gitlab_norm["protected_branch_ids"] = sorted(b["id"] for b in branches_in_gitlab)
        return gitlab_norm

    @staticmethod
    def _normalize_rule_from_config(entity_in_configuration: dict) -> dict:
        """Read the configured rule the way edit_approval_rule writes it.

        That path takes a missing list of approvers as "clear them", so an omitted one
        is compared as empty rather than as unstated. It takes a missing list of
        branches the same way, but only when the config names them neither as
        `protected_branches` nor as `protected_branch_ids`: a rule scoped by id has
        said what it wants, and is compared against the ids GitLab reports.
        """
        config_norm = dict(entity_in_configuration)
        config_norm["user_ids"] = sorted(config_norm.get("user_ids", []))
        config_norm["group_ids"] = sorted(config_norm.get("group_ids", []))
        if "protected_branch_ids" in config_norm:
            config_norm["protected_branch_ids"] = sorted(config_norm["protected_branch_ids"])
        else:
            config_norm["protected_branches"] = sorted(config_norm.get("protected_branches", []))
        return config_norm
