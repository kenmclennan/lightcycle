from lightcycle.application.workflows.repin_in_flight import RepinResponse


class NoRepin:
    def execute(self, origin):
        return RepinResponse()
