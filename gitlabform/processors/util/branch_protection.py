from logging import info, warning
from typing import Any

from gitlab.base import RESTObject

from gitlabform.processors.util.entity_matching import pair_entries


class BranchProtection:
    @staticmethod
    def map_config_to_protected_branch_get_data(our_branch_config: dict):
        """
        Normalizes the user-provided YAML config into the format returned by GitLab's GET endpoint.

        GitLab API Mappings:
        - 'merge_access_level' (Standard) -> 'merge_access_levels' (List)
        - 'allowed_to_merge' (Premium) -> 'merge_access_levels' (List)

        This transformation allows for a direct comparison between the desired state and current state.
        This method will normalize gitlabform branch_config to accommodate this.

        Args:
            our_branch_config (dict): branch configuration read from .yaml file

        Returns:
            dict: defined configuration transformed into the format returned by the Gitlab APIs
        """
        # Also see https://github.com/python-gitlab/python-gitlab/issues/2850

        info("Transforming *_access_level and allowed_to_* keys in Branch configuration")
        local_keys_to_gitlab_keys_map = {
            "merge_access_level": "merge_access_levels",
            "push_access_level": "push_access_levels",
            "unprotect_access_level": "unprotect_access_levels",
            "allowed_to_merge": "merge_access_levels",
            "allowed_to_push": "push_access_levels",
            "allowed_to_unprotect": "unprotect_access_levels",
        }
        new_branch_config = our_branch_config.copy()
        for key in our_branch_config:
            if key in local_keys_to_gitlab_keys_map.keys():
                target_key = local_keys_to_gitlab_keys_map[key]
                # *_access_level in gitlabform will have been transformed to it's int representation already if defined
                # by the user as "merge_access_level: Maintainer"
                if isinstance(our_branch_config[key], int):
                    access_level = new_branch_config.pop(key)
                    new_branch_config[target_key] = [
                        {
                            "id": None,
                            "access_level": access_level,
                            "user_id": None,
                            "group_id": None,
                            "deploy_key_id": None,
                        }
                    ]
                # allowed_to_* are lists...
                elif isinstance(our_branch_config[key], list):
                    mapped_list = []
                    for item in our_branch_config[key]:
                        # RAW PARAMETER PASSING: We ensure the core identity keys exist for comparison,
                        # but we preserve all other arbitrary keys provided by the user.
                        mapped_item = {
                            "id": None,
                            "access_level": item.get("access_level"),
                            "user_id": item.get("user_id"),
                            "group_id": item.get("group_id"),
                            "deploy_key_id": item.get("deploy_key_id"),
                            **{
                                k: v
                                for k, v in item.items()
                                if k not in ["access_level", "user_id", "group_id", "deploy_key_id", "id"]
                            },
                        }
                        mapped_list.append(mapped_item)
                    new_branch_config[target_key] = mapped_list
                    new_branch_config.pop(key)

        # this key is not present in
        # protected_branch.attributes, so _needs_update() would always
        # return True with this key present.
        new_branch_config.pop("protected")
        return new_branch_config

    @staticmethod
    def build_patch_request_data(transformed_access_levels: list[dict] | None, existing_records: tuple) -> list[dict]:
        """
        Calculates the specific payload for the PATCH (update) API.

        Every configured rule is paired with the record GitLab holds for the same rule -
        the same user, group or deploy key, or the same role for a rule that names none
        of them. A rule that ends up with a counterpart is already in GitLab and is not
        sent at all; a rule left without one is sent to be created.

        Both sides of that identity are read. The record GitLab returns for a group also
        carries an access_level of its own, so a role rule compared by access_level alone
        claims it, and the group rule of the config is then left looking absent and sent
        to be created a second time - which GitLab refuses with "Merge access levels
        group has already been taken".

        Which rule claims which record cannot depend on the order either side happens to
        come in, so the pairing is made over both lists at once rather than by walking
        them and taking the first match.

        args:
            transformed_access_levels (list[dict|None]): transformed merge_access_levels or push_access_levels or unprotect_access_levels configration generated by transform_branch_config_access_levels
            existing_records (tuple): immutable list of existing records for the protected branch in Gitlab

        returns:
            list[dict]: Data in the format required by the protected_branches PATCH api. https://docs.gitlab.com/api/protected_branches/#update-a-protected-branch
        """
        if transformed_access_levels is None:
            info("No configuration defined for this access level. No changes will be made.")
            return []

        configured_rules = [
            {key: value for key, value in configuration.items() if value is not None and key != "id"}
            for configuration in transformed_access_levels
        ]

        paired = pair_entries(list(existing_records), configured_rules, BranchProtection.rules_match)
        claimed = set(paired.values())

        patch_data = [rule for index, rule in enumerate(configured_rules) if index not in paired]
        patch_data += BranchProtection._records_to_destroy(
            [record for index, record in enumerate(existing_records) if index not in claimed],
            configured_rules,
        )

        return patch_data

    @staticmethod
    def is_role_rule(rule: dict) -> bool:
        """Whether the rule is granted to a role rather than to a user, a group or a
        deploy key."""
        return not (rule.get("user_id") or rule.get("group_id") or rule.get("deploy_key_id"))

    @staticmethod
    def rules_match(record_in_gitlab: dict, rule_in_config: dict) -> bool:
        """Whether the two describe one and the same rule.

        A rule that names a user, a group or a deploy key *is* that user, group or deploy
        key, and the access_level GitLab returns beside it takes no part. A rule that
        names none of them is its role, and can only be the same rule as a record that
        names none of them either - a group record carrying access_level 40 is not the
        role "Maintainers".
        """
        for key in ("user_id", "group_id", "deploy_key_id"):
            if rule_in_config.get(key) is not None:
                return record_in_gitlab.get(key) == rule_in_config.get(key)

        return BranchProtection.is_role_rule(record_in_gitlab) and record_in_gitlab.get(
            "access_level"
        ) == rule_in_config.get("access_level")

    @staticmethod
    def _records_to_destroy(unclaimed_records: list[dict], configured_rules: list[dict]) -> list[dict]:
        """The records to send for deletion, out of those no configured rule claimed.

        GitLabForm is additive: a record the configuration does not name is left where it
        is. The one exception is "No Access" (0), which cannot stand beside any other
        role, so a configuration asking for either removes the other.
        """
        configured_role_levels = {
            rule.get("access_level") for rule in configured_rules if BranchProtection.is_role_rule(rule)
        }
        no_access_configured = 0 in configured_role_levels
        roles_configured = any(level for level in configured_role_levels)

        to_destroy = []
        for record in unclaimed_records:
            if not BranchProtection.is_role_rule(record):
                continue
            access_level = record.get("access_level")
            if not ((no_access_configured and access_level) or (roles_configured and access_level == 0)):
                continue
            to_destroy.append(record)

        return BranchProtection._destroy_entries(to_destroy)

    @staticmethod
    def _destroy_entries(records: list[dict]) -> list[dict]:
        """The deletion entries for the given records, skipping - out loud - any record
        GitLab returned without an id, which there is no way to name in a request."""
        entries = []
        for record in records:
            record_id = record.get("id")
            if record_id is None:
                warning(f"Cannot remove the branch protection rule {record} - GitLab returned it without an id.")
                continue
            entries.append({"id": record_id, "_destroy": True})
        return entries

    @staticmethod
    def naive_access_level_diff_analyzer(_, cfg_in_gitlab: list, local_cfg: list):
        """
        Custom diff analyzer for branch rules.

        Following GitLabForm's ADDITIVE DESIGN, an update is needed if any rule
        defined in the local configuration is missing from GitLab.
        """
        for local_item in local_cfg:
            if not any(BranchProtection.rules_match(gl_item, local_item) for gl_item in cfg_in_gitlab):
                info("naive_access_level_diff_analyzer - needs_update: True (missing rule found)")
                return True

        gl_role_levels = {r.get("access_level") for r in cfg_in_gitlab if BranchProtection.is_role_rule(r)}
        local_role_levels = {r.get("access_level") for r in local_cfg if BranchProtection.is_role_rule(r)}

        if (0 in gl_role_levels and any(level for level in local_role_levels)) or (
            0 in local_role_levels and any(level for level in gl_role_levels)
        ):
            info("naive_access_level_diff_analyzer - needs_update: True (No Access / Roles conflict)")
            return True

        info("naive_access_level_diff_analyzer - needs_update: False")
        return False

    @staticmethod
    def branch_protection_config_contains_user_or_group(branch_config: dict, key: str) -> bool:
        """
        Check if any item under branch_config[key] specifies a user or group
        (via "user", "user_id", "group", or "group_id").
        """
        if key not in branch_config:
            return False
        for item in branch_config[key]:
            if isinstance(item, dict) and (
                "user" in item or "user_id" in item or "group" in item or "group_id" in item
            ):
                return True
        return False

    @staticmethod
    def get_list_attribute(protected_branch: RESTObject, attribute_name: str) -> list[Any]:
        """
        Gets list attribute such as unprotect_access_levels, merge_access_levels, push_access_levels, etc.
        Uses the python-gitlab attributes raw dict rather than direct parameter to gracefully handle when an attribute
        is not present in the API response.
        For example in CE: unprotect_access_levels is not returned on the protected_branch, so trying to access directly
        throws a runtime-exception
        """
        existing_list_value: list[Any] = []
        # Get from the "attributes" as this is the raw dict
        existing_attr = protected_branch.attributes.get(attribute_name)
        if existing_attr is not None:
            existing_list_value = existing_attr
        return existing_list_value
