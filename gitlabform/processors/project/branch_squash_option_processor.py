import sys
from logging import debug, info, error, critical
from typing import Optional

from gitlab import GitlabGetError, GitlabUpdateError
from gql.transport.exceptions import TransportQueryError

from gitlabform.constants import EXIT_INVALID_INPUT, EXIT_PROCESSING_ERROR
from gitlabform.gitlab import GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.difference_logger import DifferenceLogger

BRANCH_RULES_QUERY = """
query($fullPath: ID!, $after: String) {
  project(fullPath: $fullPath) {
    branchRules(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        name
        squashOption { option }
      }
    }
  }
}
"""

SQUASH_OPTION_CREATE_MUTATION = """
mutation($branchRuleId: ProjectsBranchRuleID!, $squashOption: SquashOptionSetting!) {
  branchRuleSquashOptionCreate(input: {branchRuleId: $branchRuleId, squashOption: $squashOption}) {
    errors
    squashOption { option }
  }
}
"""

SQUASH_OPTION_UPDATE_MUTATION = """
mutation($branchRuleId: ProjectsBranchRuleID!, $squashOption: SquashOptionSetting!) {
  branchRuleSquashOptionUpdate(input: {branchRuleId: $branchRuleId, squashOption: $squashOption}) {
    errors
    squashOption { option }
  }
}
"""

SQUASH_OPTION_DELETE_MUTATION = """
mutation($branchRuleId: ProjectsBranchRuleID!) {
  branchRuleSquashOptionDelete(input: {branchRuleId: $branchRuleId}) {
    errors
  }
}
"""


class BranchSquashOptionProcessor(AbstractProcessor):
    """
    A processor for the "squash_option" key of a branch in the "branches" section.

    It sets how merge requests targeting that branch squash their commits. The values
    are the GraphQL SquashOptionSetting enum lowercased - never, allowed, encouraged,
    always - plus "inherit", which removes the branch-level override so that the branch
    follows the project default again. A branch that does not declare the key is not
    touched. The key requires "protected: true", because the option is an attribute of
    a branch rule and a branch rule only exists for a protected branch.

    These are NOT the values of the project-level "project_settings.squash_option",
    which is a different API with a different vocabulary (never, default_off,
    default_on, always).

    Configuration example:

    branches:
      avalon:
        protected: true
        squash_option: always
      production:
        protected: true
        squash_option: never
      "release/*":
        protected: true
        squash_option: inherit
    """

    INHERIT = "inherit"

    CONFIG_TO_ENUM = {
        "never": "NEVER",
        "allowed": "ALLOWED",
        "encouraged": "ENCOURAGED",
        "always": "ALWAYS",
    }

    GITLAB_TEXT_TO_CONFIG = {
        "Do not allow": "never",
        "Allow": "allowed",
        "Encourage": "encouraged",
        "Require": "always",
    }

    PROJECT_LEVEL_VALUE_HINTS = {
        "default_off": "allowed",
        "default_on": "encouraged",
    }

    BRANCH_RULE_GID_PREFIX = "gid://gitlab/Projects::BranchRule/"

    NO_BRANCH_RULE = "(no branch rule)"

    DIFF_TITLE = "branches squash_option changes"

    def __init__(self, gitlab: GitLab, strict: bool):
        super().__init__("branches", gitlab)
        self.strict = strict
        self._branch_rules_cache: Optional[tuple[str, dict]] = None

    def _get_desired_state(self, entity_config: dict) -> dict:
        """
        Slice the `squash_option` keys out of the `branches` section.

        Branches that do not declare the key are not returned at all: "no key" means
        "this processor does not touch that branch", which is not the same as `inherit`
        ("there must be no override here").
        """
        desired: dict[str, str] = {}

        for branch_name in sorted(entity_config or {}):
            branch_config = entity_config[branch_name]
            if not isinstance(branch_config, dict) or "squash_option" not in branch_config:
                continue
            desired[branch_name] = self._validated_config_value(branch_name, branch_config)

        return desired

    def _validated_config_value(self, branch_name: str, branch_config: dict) -> str:
        value = branch_config["squash_option"]

        if not isinstance(value, str) or (value != self.INHERIT and value not in self.CONFIG_TO_ENUM):
            allowed = ", ".join(sorted(self.CONFIG_TO_ENUM) + [self.INHERIT])
            message = f"Invalid squash_option '{value}' for branch '{branch_name}'. Allowed values: {allowed}."
            if isinstance(value, str):
                hint = self.PROJECT_LEVEL_VALUE_HINTS.get(value)
                if hint:
                    message += (
                        f" '{value}' belongs to the PROJECT-level vocabulary of"
                        f" project_settings.squash_option; at branch level the same thing is '{hint}'."
                    )
                elif value.lower() in self.CONFIG_TO_ENUM or value.lower() == self.INHERIT:
                    message += f" Did you mean '{value.lower()}'? The values are lowercase."
            critical(message)
            sys.exit(EXIT_INVALID_INPUT)

        if not branch_config.get("protected"):
            critical(
                f"squash_option is set for branch '{branch_name}' which is not configured as"
                f" protected. The squash option is an attribute of a branch rule and a branch"
                f" rule only exists for a protected branch, so this could never be applied."
            )
            sys.exit(EXIT_INVALID_INPUT)

        return value

    def _get_branch_rules(self, project_and_group: str) -> dict[str, dict]:
        """
        Read every branch rule of the project, as `name -> {"id", "squash_option", "pseudo"}`.

        Two things are refused loudly instead of being resolved silently:
        * two rules with the same name - there would be no way to tell which one the
          config means;
        * an unknown value of `SquashOption.option`.
        """
        if self._branch_rules_cache is not None and self._branch_rules_cache[0] == project_and_group:
            return self._branch_rules_cache[1]

        rules: dict[str, dict] = {}
        after: Optional[str] = None

        while True:
            result = self._execute(
                BRANCH_RULES_QUERY,
                {"fullPath": project_and_group, "after": after},
                f"read branch rules of project '{project_and_group}'",
            )

            project = result.get("project")
            if project is None:
                raise GitlabGetError(f"Project '{project_and_group}' not found when reading its branch rules")

            branch_rules = project.get("branchRules")
            if branch_rules is None:
                raise GitlabGetError(
                    f"GitLab returned no branchRules for project '{project_and_group}'."
                    f" Refusing to treat that as 'there are none'."
                )

            for node in branch_rules.get("nodes") or []:
                name = node["name"]
                if name in rules:
                    critical(
                        f"Project '{project_and_group}' has more than one branch rule named '{name}'"
                        f" ({rules[name]['id']} and {node['id']}). Which one a squash_option in the"
                        f" config refers to is ambiguous, so nothing is applied."
                    )
                    sys.exit(EXIT_PROCESSING_ERROR)

                rules[name] = {
                    "id": node["id"],
                    "squash_option": self._config_value_of(project_and_group, name, node.get("squashOption")),
                    "pseudo": not node["id"].startswith(self.BRANCH_RULE_GID_PREFIX),
                }

            page_info = branch_rules.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
            if not after:
                critical(
                    f"GitLab reports more branch rules for project '{project_and_group}' but returned"
                    f" no cursor to read them. Refusing to work with a truncated list."
                )
                sys.exit(EXIT_PROCESSING_ERROR)

        self._branch_rules_cache = (project_and_group, rules)
        return rules

    def _config_value_of(self, project_and_group: str, branch_name: str, squash_option: Optional[dict]) -> str:
        if squash_option is None:
            return self.INHERIT

        text = squash_option.get("option")
        value = self.GITLAB_TEXT_TO_CONFIG.get(text) if isinstance(text, str) else None
        if value is None:
            critical(
                f"GitLab returned an unknown squash option '{text}' for branch '{branch_name}' of"
                f" project '{project_and_group}'. This field is a human-readable description and"
                f" GitLab has apparently changed it; gitlabform will not guess what it means."
                f" Known values: {', '.join(sorted(self.GITLAB_TEXT_TO_CONFIG))}."
            )
            sys.exit(EXIT_PROCESSING_ERROR)

        return value

    def _get_current_state(self, project_and_group: str) -> dict:
        return {
            name: rule["squash_option"]
            for name, rule in self._get_branch_rules(project_and_group).items()
            if not rule["pseudo"]
        }

    def _print_diff(self, project_or_project_and_group: str, entity_config, diff_only_changed: bool):
        self._branch_rules_cache = None

        desired = self._get_desired_state(entity_config)
        if not desired:
            debug("No branch declares squash_option - nothing to diff.")
            return

        current = self._get_current_state(project_or_project_and_group)
        rules = self._get_branch_rules(project_or_project_and_group)

        current_for_diff = {}
        for branch_name in desired:
            self._refuse_pseudo_rule(project_or_project_and_group, branch_name, rules.get(branch_name))
            current_for_diff[branch_name] = current.get(branch_name, self.NO_BRANCH_RULE)

        DifferenceLogger.log_diff(
            self.DIFF_TITLE,
            current_for_diff,
            desired,
            only_changed=diff_only_changed,
        )

    def _process_configuration(self, project_and_group: str, configuration: dict):
        self._branch_rules_cache = None

        desired = self._get_desired_state(configuration.get("branches") or {})
        if not desired:
            debug("No branch declares squash_option - nothing to do.")
            return

        rules = self._get_branch_rules(project_and_group)

        for branch_name in sorted(desired):
            rule = rules.get(branch_name)
            self._refuse_pseudo_rule(project_and_group, branch_name, rule)

            if rule is None:
                message = (
                    f"squash_option is configured for branch '{branch_name}' of project"
                    f" '{project_and_group}' but that branch has no branch rule - it is not"
                    f" protected. The squash option was NOT applied."
                )
                if self.strict:
                    critical(message)
                    sys.exit(EXIT_PROCESSING_ERROR)
                error(message)
                continue

            self._apply_squash_option(project_and_group, branch_name, rule, desired[branch_name])

    def _refuse_pseudo_rule(self, project_and_group: str, branch_name: str, rule: Optional[dict]):
        if rule is not None and rule["pseudo"]:
            critical(
                f"'{branch_name}' of project '{project_and_group}' is not a branch - it is GitLab's"
                f" project-wide pseudo rule ({rule['id']}). Its squash option IS the project"
                f" default; set it with project_settings.squash_option (which uses the values"
                f" never / default_off / default_on / always) instead."
            )
            sys.exit(EXIT_INVALID_INPUT)

    def _apply_squash_option(self, project_and_group: str, branch_name: str, rule: dict, wanted: str):
        current = rule["squash_option"]
        rule_id = rule["id"]

        if current == wanted:
            debug(f"Branch '{branch_name}': squash_option is already '{wanted}'.")
            return

        if wanted == self.INHERIT:
            info(f"Removing the squash_option override of branch '{branch_name}' (was '{current}').")
            self._mutate(
                SQUASH_OPTION_DELETE_MUTATION,
                {"branchRuleId": rule_id},
                "branchRuleSquashOptionDelete",
                f"remove the squash_option override of branch '{branch_name}' of project '{project_and_group}'",
            )
            return

        enum_value = self.CONFIG_TO_ENUM[wanted]

        if current == self.INHERIT:
            info(f"Setting squash_option of branch '{branch_name}' to '{wanted}'.")
            mutation, field = SQUASH_OPTION_CREATE_MUTATION, "branchRuleSquashOptionCreate"
        else:
            info(f"Changing squash_option of branch '{branch_name}' from '{current}' to '{wanted}'.")
            mutation, field = SQUASH_OPTION_UPDATE_MUTATION, "branchRuleSquashOptionUpdate"

        self._mutate(
            mutation,
            {"branchRuleId": rule_id, "squashOption": enum_value},
            field,
            f"set squash_option of branch '{branch_name}' of project '{project_and_group}' to '{wanted}'",
        )

    def _execute(self, document: str, variables: dict, description: str) -> dict:
        try:
            return self.gl.graphql.execute(document, variable_values=variables)
        except TransportQueryError as e:
            message = e.errors[0]["message"] if e.errors else "unknown GraphQL error"
            raise GitlabGetError(f"Failed to {description}: {message}")

    def _mutate(self, document: str, variables: dict, field: str, description: str) -> dict:
        try:
            result = self.gl.graphql.execute(document, variable_values=variables)
        except TransportQueryError as e:
            message = e.errors[0]["message"] if e.errors else "unknown GraphQL error"
            raise GitlabUpdateError(f"Failed to {description}: {message}")

        payload = result.get(field) or {}
        errors = payload.get("errors") or []
        if errors:
            raise GitlabUpdateError(f"Failed to {description}: {errors}")

        return payload
