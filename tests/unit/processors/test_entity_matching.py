from gitlabform.processors.abstract_processor import AbstractProcessor
from gitlabform.processors.util.entity_matching import align_entries, pair_entries


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


def _align(entries_in_gitlab: list, entries_in_configuration: list) -> list:
    return align_entries(entries_in_gitlab, entries_in_configuration, AbstractProcessor._entries_match)


class TestAlignEntries:
    def test__a_paired_entry_holds_only_what_its_counterpart_declares(self):
        in_gitlab = [{"id": 12, "access_level": None, "group_id": 15, "group_inheritance_type": 0}]
        in_configuration = [{"group_id": 15}]

        assert _align(in_gitlab, in_configuration) == [{"group_id": 15}]

    def test__a_paired_entry_keeps_the_key_order_of_its_counterpart(self):
        in_gitlab = [{"required_approvals": 2, "id": 12, "group_id": 15}]
        in_configuration = [{"group_id": 15, "required_approvals": 2}]

        assert list(_align(in_gitlab, in_configuration)[0]) == ["group_id", "required_approvals"]

    def test__a_key_the_configuration_declares_and_gitlab_does_not_report_stays_absent(self):
        in_gitlab = [{"id": 12, "group_id": 15}]
        in_configuration = [{"group_id": 15, "group_inheritance_type": 1}]

        assert _align(in_gitlab, in_configuration) == [{"group_id": 15}]

    def test__an_entry_no_configured_entry_claims_is_left_whole(self):
        in_gitlab = [{"id": 12, "group_id": 15, "access_level_description": "leads"}]
        in_configuration = [{"group_id": 16}]

        assert _align(in_gitlab, in_configuration) == [{"id": 12, "group_id": 15, "access_level_description": "leads"}]

    def test__paired_entries_come_in_the_order_of_the_configuration(self):
        in_gitlab = [{"id": 1, "user_id": 2}, {"id": 2, "user_id": 1}]
        in_configuration = [{"user_id": 1}, {"user_id": 2}]

        assert _align(in_gitlab, in_configuration) == [{"user_id": 1}, {"user_id": 2}]

    def test__the_unclaimed_entries_come_after_the_paired_ones(self):
        in_gitlab = [{"id": 1, "user_id": 3}, {"id": 2, "user_id": 1}]
        in_configuration = [{"user_id": 1}]

        assert _align(in_gitlab, in_configuration) == [{"user_id": 1}, {"id": 1, "user_id": 3}]

    def test__an_entry_that_is_not_a_map_is_left_as_it_is(self):
        assert _align(["api", "read_api"], ["api"]) == ["api", "read_api"]
