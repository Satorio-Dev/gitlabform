from typing import Any, Callable


def pair_entries(
    entries_in_gitlab: list,
    entries_in_configuration: list,
    matches: Callable[[Any, Any], bool],
) -> dict[int, int]:
    """Pair every configured entry with a distinct entry in GitLab that it matches.

    :return: {index in the configuration: index in GitLab}, holding only the entries
        that could be paired. An entry with no counterpart is absent from the result.

    A configured entry often matches more than one entry in GitLab - "access_level: 40"
    matches every rule carrying it - so a pairing made in one pass by first match can
    leave a later entry without a counterpart where another pairing would have served
    both. Whenever the only counterpart left is already taken, the entry holding it is
    asked to move (Kuhn's augmenting path), so the result holds as many pairs as any
    pairing can.
    """
    taken: dict[int, int] = {}

    def take(configuration_index: int, tried: set[int]) -> bool:
        for gitlab_index in range(len(entries_in_gitlab)):
            if gitlab_index in tried:
                continue
            if not matches(entries_in_gitlab[gitlab_index], entries_in_configuration[configuration_index]):
                continue

            tried.add(gitlab_index)
            if gitlab_index not in taken or take(taken[gitlab_index], tried):
                taken[gitlab_index] = configuration_index
                return True

        return False

    for configuration_index in range(len(entries_in_configuration)):
        take(configuration_index, set())

    return {configuration_index: gitlab_index for gitlab_index, configuration_index in taken.items()}


def align_entries(
    entries_in_gitlab: list,
    entries_in_configuration: list,
    matches: Callable[[Any, Any], bool],
) -> list:
    """The GitLab entries as the matcher reads them beside the configuration.

    :return: the paired GitLab entries, each holding only the keys its counterpart
        declares and in that counterpart's order, followed by the entries no configured
        entry claimed, whole.

    An entry GitLab returns carries more than the entry the configuration declares: the
    access_level it keeps beside a user id, the description it composes out of the two,
    the id it assigned. The matcher pairs the two regardless - that is what decides
    whether anything is sent - so a reader that compares them as they stand announces a
    difference the apply path will not act on.

    An entry with no counterpart is left whole, because there the difference is real and
    every key of it is worth reading.
    """
    paired = pair_entries(entries_in_gitlab, entries_in_configuration, matches)
    claimed = set(paired.values())

    aligned = [
        _as_declared(entries_in_gitlab[paired[configuration_index]], entry)
        for configuration_index, entry in enumerate(entries_in_configuration)
        if configuration_index in paired
    ]

    return aligned + [entry for index, entry in enumerate(entries_in_gitlab) if index not in claimed]


def _as_declared(entry_in_gitlab: Any, entry_in_configuration: Any) -> Any:
    """The GitLab entry holding only the keys the configured entry declares.

    A key the configuration declares and GitLab does not report stays absent rather than
    arriving as a null, so that "GitLab holds no answer to this" reads as what it is.
    """
    if not isinstance(entry_in_gitlab, dict) or not isinstance(entry_in_configuration, dict):
        return entry_in_gitlab

    return {key: entry_in_gitlab[key] for key in entry_in_configuration if key in entry_in_gitlab}
