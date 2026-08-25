import sys
from logging import critical

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import GitLab
from gitlabform.processors.defining_keys import And, Key
from gitlabform.processors.multiple_entities_processor import MultipleEntitiesProcessor


class FreezePeriodsProcessor(MultipleEntitiesProcessor):
    """The "freeze_periods" section - deploy freezes of a project.

    A freeze period has no name in GitLab, so the pair (freeze_start, freeze_end) is
    what identifies it. The key each period is written under in the configuration is a
    label for a human and travels nowhere.

    That identity has a consequence worth stating: rewriting one of the two cron
    expressions does not edit a period, it declares a different one. The former period
    then shows on the removal side of the dry-run diff - "(will be removed by enforce)"
    where enforce is on, "(only in GitLab)" where it is not - and the latter is created.
    Only cron_timezone can be edited in place.
    """

    diff_ignored_keys = MultipleEntitiesProcessor.diff_ignored_keys | {
        "created_at",
        "updated_at",
    }

    def __init__(self, gitlab: GitLab):
        super().__init__(
            "freeze_periods",
            gitlab,
            list_method_name="get_freeze_periods",
            add_method_name="add_freeze_period",
            delete_method_name="delete_freeze_period",
            defining=And(Key("freeze_start"), Key("freeze_end")),
            required_to_create_or_update=And(Key("freeze_start"), Key("freeze_end")),
            edit_method_name="edit_freeze_period",
        )

    def _get_desired_state(self, entity_config: dict) -> dict:
        """The config side of the diff, keyed the way the current state is keyed.

        Two periods the configuration declares under different labels but with the same
        pair of cron expressions are one entity to GitLab and would collapse into one
        line here, the second silently overwriting the first. The apply path already
        refuses that config; so does this one, naming both labels, rather than showing a
        dry run that no apply will ever perform.
        """
        desired: dict = {}
        labels: dict = {}
        for label, freeze_period in entity_config.items():
            if label == "enforce" or not isinstance(freeze_period, dict):
                continue
            if not self.defining.contains(freeze_period):
                critical(
                    f"Freeze period '{label}' in {self.configuration_name} does not declare"
                    f" {self.defining.explain()}, so there is nothing to tell it apart by."
                )
                sys.exit(EXIT_INVALID_INPUT)
            identity = self.defining.identity(freeze_period)
            if identity in desired:
                critical(
                    f"Freeze periods '{labels[identity]}' and '{label}' in {self.configuration_name}"
                    f" are the same in terms of their defining keys: {self.defining.explain()}"
                )
                sys.exit(EXIT_INVALID_INPUT)
            labels[identity] = label
            desired[identity] = dict(sorted(freeze_period.items()))
        return desired
