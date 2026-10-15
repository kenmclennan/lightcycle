def with_engine_fragments(root, config):
    if not root or config is None:
        return root
    return [config.prompts_root(), root]
