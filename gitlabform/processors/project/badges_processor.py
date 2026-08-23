from typing import Any

from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import Key, And
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class BadgesProcessor(MultipleEntitiesProcessor):
    diff_ignored_keys = MultipleEntitiesProcessor.diff_ignored_keys | {
        "rendered_link_url",
        "rendered_image_url",
        "kind",
    }

    def __init__(self, gitlab: GitLab):
        super().__init__(
            "badges",
            gitlab,
            list_method_name="get_project_badges",
            add_method_name="add_project_badge",
            delete_method_name="delete_project_badge",
            defining=Key("name"),
            required_to_create_or_update=And(Key("name"), Key("link_url"), Key("image_url")),
            edit_method_name="edit_project_badge",
        )

    def _get_current_state(self, project_and_group: str) -> dict[str, dict[str, Any]]:
        return {
            badge["name"]: {
                k: badge[k] for k in sorted(badge) if k not in {"id", "kind", "rendered_link_url", "rendered_image_url"}
            }
            for badge in self.list_method(project_and_group)
        }

    def _get_desired_state(self, entity_config: dict) -> dict[str, dict[str, Any]]:
        return {
            badge["name"]: dict(sorted(badge.items()))
            for alias, badge in entity_config.items()
            if alias != "enforce" and isinstance(badge, dict)
        }
