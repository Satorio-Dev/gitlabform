import sys
from logging import critical

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import And, Key
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class DeployKeysProcessor(MultipleEntitiesProcessor):
    def __init__(self, gitlab: GitLab):
        super().__init__(
            "deploy_keys",
            gitlab,
            list_method_name="get_deploy_keys",
            add_method_name="post_deploy_key",
            delete_method_name="delete_deploy_key",
            defining=Key("title"),
            required_to_create_or_update=And(Key("title"), Key("key")),
            # DO NOT use put_deploy_key for update as it can only update key's title,
            # but NOT the value (according to https://docs.gitlab.com/ee/api/deploy_keys.html#update-deploy-key)
        )

    def _get_current_state(self, project_and_group: str) -> dict:
        return {
            deploy_key["title"]: self._comparable_deploy_key(deploy_key)
            for deploy_key in self.list_method(project_and_group)
        }

    def _get_desired_state(self, entity_config: dict) -> dict:
        desired: dict = {}
        for alias, deploy_key in entity_config.items():
            if alias == "enforce" or not isinstance(deploy_key, dict):
                continue
            title = deploy_key.get("title")
            if title in desired:
                critical(
                    f"Deploy keys in {self.configuration_name} have the same title '{title}'"
                    f" - cannot diff them unambiguously."
                )
                sys.exit(EXIT_INVALID_INPUT)
            desired[title] = self._comparable_deploy_key(deploy_key)
        return desired

    @staticmethod
    def _comparable_deploy_key(deploy_key: dict) -> dict:
        server_side_noise = {
            "id",
            "fingerprint",
            "fingerprint_sha256",
            "created_at",
            "last_used_at",
            "projects_with_write_access",
        }
        return {
            k: deploy_key[k] for k in sorted(deploy_key) if k not in server_side_noise and deploy_key[k] is not None
        }
