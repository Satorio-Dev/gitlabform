class SomeWritesFailed(Exception):
    pass


class FailedWrites:
    """The writes of one node that GitLab refused, held until the node is done with.

    A refused write that is logged and walked past leaves the run green, the summary
    clean and the world unchanged - the operator is told the config was applied when
    it was not. Raising on the first refusal would end that lie but would also drop
    every write the node had left, so the refusals are collected instead: the rest of
    the node is written, and the node still ends in the failed list.
    """

    def __init__(self, what: str):
        self.what = what
        self.messages: list[str] = []

    def start(self) -> None:
        self.messages = []

    def record(self, message: str) -> None:
        self.messages.append(message)

    def raise_if_any(self, node: str) -> None:
        if self.messages:
            raise SomeWritesFailed(f"{self.what} in {node}: {len(self.messages)} failed - " + "; ".join(self.messages))
