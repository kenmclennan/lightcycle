class AlwaysConfirmed:
    def poll_epoch(self):
        return 0

    def confirmed_after(self, pr, epoch):
        return True

    def hold_prs(self, prs):
        return None


class NeverConfirmed:
    def poll_epoch(self):
        return 0

    def confirmed_after(self, pr, epoch):
        return False

    def hold_prs(self, prs):
        return None
