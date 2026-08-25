from gitlabform.gitlab.projects import GitLabProjects


class GitLabProjectFreezePeriods(GitLabProjects):
    """The project Freeze Periods API - https://docs.gitlab.com/api/freeze_periods/

    A freeze period carries no name in GitLab. What tells one apart is the pair of cron
    expressions it is made of, or the id GitLab gave it, and nothing else.

    The endpoint takes exactly three fields, so exactly those three are ever sent: a
    key the configuration carries for GitLabForm's own use is not a field of this API
    and must not travel to it.
    """

    API_FIELDS = ("freeze_start", "freeze_end", "cron_timezone")

    def get_freeze_periods(self, project_and_group_name):
        return self._make_requests_to_api("projects/%s/freeze_periods", project_and_group_name)

    def add_freeze_period(self, project_and_group_name, freeze_period_in_config):
        return self._make_requests_to_api(
            "projects/%s/freeze_periods",
            project_and_group_name,
            method="POST",
            data=self._api_payload(freeze_period_in_config),
            expected_codes=201,
        )

    def edit_freeze_period(self, project_and_group_name, freeze_period_in_gitlab, freeze_period_in_config):
        return self._make_requests_to_api(
            "projects/%s/freeze_periods/%s",
            (project_and_group_name, freeze_period_in_gitlab["id"]),
            method="PUT",
            data=self._api_payload(freeze_period_in_config),
        )

    def delete_freeze_period(self, project_and_group_name, freeze_period_in_gitlab):
        """404 means it is already gone, so it is accepted here for idempotency."""
        return self._make_requests_to_api(
            "projects/%s/freeze_periods/%s",
            (project_and_group_name, freeze_period_in_gitlab["id"]),
            method="DELETE",
            expected_codes=[200, 204, 404],
        )

    @classmethod
    def _api_payload(cls, freeze_period_in_config: dict) -> dict:
        return {field: freeze_period_in_config[field] for field in cls.API_FIELDS if field in freeze_period_in_config}
