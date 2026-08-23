from typing import Union

from gitlab.v4.objects import Group, Project

from gitlabform.gitlab import GitLab
from gitlabform.processors.shared.access_tokens_processor import AccessTokensProcessor


class GroupAccessTokensProcessor(AccessTokensProcessor):
    """https://docs.gitlab.com/api/group_access_tokens/"""

    def __init__(self, gitlab: GitLab):
        super().__init__("group_access_tokens", gitlab)

    def _get_container(self, project_or_group: str) -> Union[Group, Project]:
        return self.gl.get_group_by_path_cached(project_or_group)
