from lightcycle.ports.health_icon import HealthIconPort


class FakeHealthIcon(HealthIconPort):
    def __init__(self):
        self.transmitted = []
        self.deleted = 0
        self._sent = set()

    def transmit(self, image_id, png, columns):
        if image_id in self._sent:
            return
        self._sent.add(image_id)
        self.transmitted.append((image_id, png, columns))

    def delete_all(self):
        self.deleted += 1
        self._sent = set()
