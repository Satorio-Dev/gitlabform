import sys
from logging import critical

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import Key, And
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class GroupBadgesProcessor(MultipleEntitiesProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__(
            "group_badges",
            gitlab,
            list_method_name="get_group_badges",
            add_method_name="add_group_badge",
            delete_method_name="delete_group_badge",
            defining=Key("name"),
            required_to_create_or_update=And(Key("name"), Key("link_url"), Key("image_url")),
            edit_method_name="edit_group_badge",
        )

    def _get_current_state(self, group: str) -> dict:
        return {badge["name"]: self._comparable_badge(badge) for badge in self.list_method(group)}

    def _get_desired_state(self, entity_config: dict) -> dict:
        desired: dict = {}
        for alias, badge in entity_config.items():
            if alias == "enforce" or not isinstance(badge, dict):
                continue
            name = badge.get("name")
            if name in desired:
                critical(
                    f"Badges in {self.configuration_name} have the same name '{name}'"
                    f" - cannot diff them unambiguously."
                )
                sys.exit(EXIT_INVALID_INPUT)
            desired[name] = self._comparable_badge(badge)
        return desired

    @staticmethod
    def _comparable_badge(badge: dict) -> dict:
        server_side_noise = {"id", "rendered_link_url", "rendered_image_url", "kind"}
        return {k: badge[k] for k in sorted(badge) if k not in server_side_noise and badge[k] is not None}
