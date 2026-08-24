from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.entity_matching import pair_entries


def _pair(entries_in_gitlab: list, entries_in_configuration: list) -> dict:
    return pair_entries(entries_in_gitlab, entries_in_configuration, AbstractProcessor._entries_match)


class TestPairEntries:
    def test__an_entry_gives_up_its_counterpart_when_it_is_the_only_one_another_entry_has(self):
        in_gitlab = [
            {"id": 1, "access_level": 40, "user_id": None},
            {"id": 2, "access_level": 40, "user_id": 15},
        ]
        in_configuration = [{"access_level": 40, "user_id": 15}, {"access_level": 40}]

        assert _pair(in_gitlab, in_configuration) == {0: 1, 1: 0}

    def test__an_entry_with_no_counterpart_is_absent_from_the_pairing(self):
        in_gitlab = [{"id": 1, "access_level": 40}]
        in_configuration = [{"access_level": 40}, {"access_level": 30}]

        assert _pair(in_gitlab, in_configuration) == {0: 0}

    def test__no_entry_in_gitlab_is_paired_with_more_than_one_entry_in_the_configuration(self):
        in_gitlab = [{"id": 1, "access_level": 40}]
        in_configuration = [{"access_level": 40}, {"access_level": 40}]

        assert _pair(in_gitlab, in_configuration) == {0: 0}
