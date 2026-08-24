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
