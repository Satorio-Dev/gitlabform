import hashlib
import json
from itertools import starmap

from logging import info


# Simple function to create strings for values which should be hidden
# example: <secret b2c1a982>
def hide(text: str):
    return f"<secret {hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]}>"


REMOVED_BY_ENFORCE = "(will be removed by enforce)"
ONLY_IN_GITLAB = "(only in GitLab)"
TO_BE_DELETED = "(will be deleted)"
NOTHING_TO_DELETE = "(not in GitLab - nothing to delete)"


class DifferenceLogger:
    @staticmethod
    def log_diff(
        subject,
        current_config,
        config_to_apply,
        only_changed=False,
        hide_entries=None,
        test=False,
        removed_marker=None,
    ):
        """Render the difference between the current state and the one to apply.

        :param removed_marker: what to show in place of the "to be applied" value of a
            key that ``current_config`` has and ``config_to_apply`` does not. Passing it
            is what enables that side of the diff at all.
        """
        # Compose values in list of `[key, from_config, from_server]``
        changes = [
            [
                k,
                json.dumps(current_config.get(k, "???") if isinstance(current_config, dict) else "???"),
                json.dumps(v),
            ]
            for k, v in config_to_apply.items()
        ]

        # Remove unchanged if needed
        if only_changed:
            # due to `filter` returning an iterator, we have to wrap it
            # in `list()` to get the values and assign back to `changes`,
            # otherwise `changes` is not what we expect it to be later :)
            changes = list(filter(lambda i: i[1] != i[2], changes))

        # Hide secrets
        if hide_entries:
            changes = list(
                map(
                    lambda i: ([i[0], hide(i[1]), hide(i[2])] if i[0] in hide_entries else i),
                    changes,
                )
            )

        if removed_marker is not None and isinstance(current_config, dict):
            for key in current_config:
                if key in config_to_apply:
                    continue
                current_value = json.dumps(current_config[key])
                if hide_entries and key in hide_entries:
                    current_value = hide(current_value)
                changes.append([key, current_value, removed_marker])

        # There is the potential that no changes need to be shown, which
        # results in the calls to max() later on to fail. Instead, opting
        # to return early with an emtpy string, since no changes were identified
        if len(changes) == 0:
            return ""

        # calculate field size for nice formatting
        max_key_len = str(max(map(lambda i: len(i[0]), changes)))
        max_val_1 = str(max(map(lambda i: len(i[1]), changes)))
        max_val_2 = str(max(map(lambda i: len(i[2]), changes)))

        # generate placeholders for output pattern: `     value: before  => after   `
        pattern = "{:>" + max_key_len + "}: {:<" + max_val_1 + "} => {:<" + max_val_2 + "}"

        # create string
        text = "{subject}:\n{diff}".format(subject=subject, diff="\n".join(starmap(pattern.format, changes)))

        if test:
            return text
        else:
            info(text)
