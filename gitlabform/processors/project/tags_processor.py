import sys
from logging import debug, warning, critical, error

from gitlabform.constants import EXIT_PROCESSING_ERROR
from gitlabform.gitlab import GitLab
from gitlab import GitlabDeleteError, GitlabGetError
from gitlabform.processors.abstract_processor import AbstractProcessor


class TagsProcessor(AbstractProcessor):
    def __init__(self, gitlab: GitLab, strict: bool):
        super().__init__("tags", gitlab)
        self.strict = strict

    def _get_current_state(self, project_and_group: str) -> dict:
        """Protected tags, keyed by tag name, for the centralized dry-run diff.
        Tags that are not protected are not listed by this endpoint, so a tag
        configured with "protected: false" shows up as "???" on the current side."""
        project = self.gl.get_project_by_path_cached(project_and_group)
        current = {}
        for tag in project.protectedtags.list(get_all=True):
            tag_dict = tag.asdict()
            current[tag_dict["name"]] = {
                "protected": True,
                "allowed_to_create": self._normalize_access_levels(tag_dict.get("create_access_levels", [])),
            }
        return current

    def _get_desired_state(self, entity_config: dict) -> dict:
        desired: dict = {}
        for tag in sorted(entity_config):
            tag_config = entity_config[tag]
            if not tag_config.get("protected"):
                desired[tag] = {"protected": False}
                continue
            allowed_to_create = [
                self._resolve_allowed_to_create(config) for config in tag_config.get("allowed_to_create", [])
            ]
            if "create_access_level" in tag_config:
                allowed_to_create.append({"access_level": tag_config["create_access_level"]})
            desired[tag] = {
                "protected": True,
                "allowed_to_create": self._normalize_access_levels(allowed_to_create),
            }
        return desired

    def _resolve_allowed_to_create(self, config: dict) -> dict:
        if "user" in config:
            user_id = self.gl.get_user_id_cached(config["user"])
            if user_id is not None:
                return {"user_id": user_id}
        elif "group" in config:
            try:
                return {"group_id": self.gl.get_group_by_path_cached(config["group"]).get_id()}
            except GitlabGetError:
                pass
        return config

    @staticmethod
    def _normalize_access_levels(access_levels: list) -> list:
        """One entry per rule, without the ids and descriptions GitLab adds, and
        without the access_level it reports next to a named user or group - the config
        cannot express that one and the apply path never sends it."""
        noise = ("id", "access_level_description")
        normalized = [{k: v for k, v in entry.items() if k not in noise and v is not None} for entry in access_levels]

        for entry in normalized:
            if "user_id" in entry or "group_id" in entry:
                entry.pop("access_level", None)

        return sorted(normalized, key=lambda entry: sorted(entry.items()))

    def _process_configuration(self, project_and_group: str, configuration: dict):
        project = self.gl.get_project_by_path_cached(name=project_and_group, lazy=True)

        for tag in sorted(configuration["tags"]):
            try:
                if configuration["tags"][tag]["protected"]:
                    allowed_to_create = []

                    if "allowed_to_create" in configuration["tags"][tag]:
                        access_levels = set()
                        user_ids = set()
                        group_ids = set()

                        requested_configuration = configuration["tags"][tag]["allowed_to_create"]

                        for config in requested_configuration:
                            if "access_level" in config:
                                access_levels.add(config["access_level"])
                            elif "user_id" in config:
                                user_ids.add(config["user_id"])
                            elif "user" in config:
                                user_id = self.gl.get_user_id_cached(config["user"])
                                if user_id is None:
                                    error(
                                        f"Could not find User '{config["user"]}' on the Instance, cannot Protect "
                                        f"Tag with them"
                                    )
                                    raise GitlabGetError(
                                        f"_process_configuration - No users found when searching for username {config["user"]}",
                                        404,
                                    )

                                user_ids.add(user_id)
                            elif "group_id" in config:
                                group_ids.add(config["group_id"])
                            elif "group" in config:
                                try:
                                    gitlab_group = self.gl.get_group_by_path_cached(config["group"])
                                except GitlabGetError as e:
                                    error(
                                        f"Could not find Group '{config["group"]}' on the Instance, cannot Protect "
                                        f"Tag with them"
                                    )
                                    raise e

                                group_ids.add(gitlab_group.get_id())

                        for val in access_levels:
                            allowed_to_create.append({"access_level": val})

                        for val in user_ids:
                            allowed_to_create.append({"user_id": val})

                        for val in group_ids:
                            allowed_to_create.append({"group_id": val})

                    create_access_level = (
                        configuration["tags"][tag]["create_access_level"]
                        if "create_access_level" in configuration["tags"][tag]
                        else None
                    )

                    debug("Setting tag '%s' as *protected*", tag)
                    try:
                        # try to unprotect first
                        project.protectedtags.delete(tag)
                    except GitlabDeleteError:
                        pass

                    data = {}
                    data["name"] = tag
                    if allowed_to_create is not None:
                        data["allowed_to_create"] = allowed_to_create
                    if create_access_level is not None:
                        data["create_access_level"] = create_access_level
                    project.protectedtags.create(data)
                else:
                    debug("Setting tag '%s' as *unprotected*", tag)
                    project.protectedtags.delete(tag)
            except GitlabDeleteError:
                message = f"Tag '{tag}' not found when trying to unprotect it!"
                if self.strict:
                    critical(message)
                    sys.exit(EXIT_PROCESSING_ERROR)
                else:
                    warning(message)
            except GitlabGetError as e:
                if self.strict:
                    critical(
                        e,
                    )
                    sys.exit(EXIT_PROCESSING_ERROR)
                else:
                    warning(message)
