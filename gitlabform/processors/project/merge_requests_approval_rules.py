from typing import Any

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
        return {
            rule["name"]: dict(sorted(self._normalize_rule_from_config(rule).items()))
            for alias, rule in entity_config.items()
            if alias != "enforce" and isinstance(rule, dict)
        }

    @staticmethod
    def _normalize_rule_from_gitlab(entity_in_gitlab: dict) -> dict:
        # GitLab returns users/groups as lists of objects and protected_branches as list
        # of objects with a "name" field, while the config (post-transform) has user_ids /
        # group_ids as int lists and protected_branches as list of names. Without
        # normalization the base _needs_update always triggers an update, even when nothing
        # changed. We normalize both sides unconditionally so keys line up regardless of
        # whether GitLab omitted an empty list or the user omitted the field in config.
        gitlab_norm = dict(entity_in_gitlab)
        gitlab_norm["user_ids"] = sorted(u["id"] for u in gitlab_norm.pop("users", []))
        gitlab_norm["group_ids"] = sorted(g["id"] for g in gitlab_norm.pop("groups", []))
        gitlab_norm["protected_branches"] = sorted(b["name"] for b in gitlab_norm.get("protected_branches", []))
        return gitlab_norm

    @staticmethod
    def _normalize_rule_from_config(entity_in_configuration: dict) -> dict:
        # edit_approval_rule treats missing user_ids/group_ids/protected_branches
        # in config as "clear them", so mirror that here to keep the comparison honest.
        config_norm = dict(entity_in_configuration)
        config_norm["user_ids"] = sorted(config_norm.get("user_ids", []))
        config_norm["group_ids"] = sorted(config_norm.get("group_ids", []))
        config_norm["protected_branches"] = sorted(config_norm.get("protected_branches", []))
        return config_norm
