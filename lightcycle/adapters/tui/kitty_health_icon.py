import base64

from lightcycle.ports.health_icon import HealthIconPort

CHUNK_BYTES = 4096


class TuiTerminalWriter:
    def __init__(self):
        self._target = None

    def bind(self, write):
        self._target = write

    def __call__(self, data):
        if self._target is not None:
            self._target(data)


class KittyHealthIconAdapter(HealthIconPort):
    def __init__(self, write):
        self._write = write
        self._sent = []

    def transmit(self, image_id, png, columns):
        if image_id in self._sent:
            return
        payload = base64.standard_b64encode(png).decode("ascii")
        chunks = [payload[i:i + CHUNK_BYTES] for i in range(0, len(payload), CHUNK_BYTES)] or [""]
        for index, chunk in enumerate(chunks):
            more = 1 if index < len(chunks) - 1 else 0
            if index == 0:
                control = "f=100,a=T,U=1,i=%d,c=%d,r=2,q=2,m=%d" % (image_id, columns, more)
            else:
                control = "m=%d,q=2" % more
            self._write("\x1b_G%s;%s\x1b\\" % (control, chunk))
        self._sent.append(image_id)

    def delete_all(self):
        for image_id in self._sent:
            self._write("\x1b_Ga=d,d=I,i=%d,q=2\x1b\\" % image_id)
        self._sent = []
