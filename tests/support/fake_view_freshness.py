class AlwaysConfirmed:
    def poll_epoch(self):
        return 0

    def confirmed_after(self, pr, epoch):
        return True


class NeverConfirmed:
    def poll_epoch(self):
        return 0

    def confirmed_after(self, pr, epoch):
        return False
