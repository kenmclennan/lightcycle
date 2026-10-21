class UseCaseError(Exception):
    pass


class FieldRefusalError(UseCaseError):
    def __init__(self, refusal):
        super().__init__(refusal)
        self.refusal = refusal
