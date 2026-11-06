from dataclasses import replace

from lightcycle.ports.github import StackLayer

STACK_URL = "https://github.com/acme/widget/stack/3"
TRUNK = "main"


def layer_url(n):
    return "https://github.com/acme/widget/pull/%d" % n


def head_ref(n):
    return "layer-%d" % n


def build_stack(count, states=None, first=1):
    states = states or {}
    layers = []
    below = TRUNK
    for i in range(count):
        n = first + i
        state = states.get(n, "open")
        layers.append(StackLayer(
            number=n, url=layer_url(n), head_ref=head_ref(n), base_ref=below,
            head_sha="sha-%d" % n, state=state,
        ))
        if state != "merged":
            below = head_ref(n)
    return tuple(layers)


def with_state(layers, number, state):
    changed = [replace(l, state=state) if l.number == number else l for l in layers]
    return rederive(changed)


def rederive(layers):
    out = []
    below = TRUNK
    for layer in layers:
        out.append(replace(layer, base_ref=below))
        if layer.state != "merged":
            below = layer.head_ref
    return tuple(out)


def base_keys_for(layers, overrides=None):
    keys = {}
    for layer in layers:
        keys[layer.url] = "acme/widget@%s" % layer.base_ref
    for n, base in (overrides or {}).items():
        keys[layer_url(n)] = "acme/widget@%s" % base
    return keys


def head_shas_for(layers):
    return {layer.url: layer.head_sha for layer in layers}
