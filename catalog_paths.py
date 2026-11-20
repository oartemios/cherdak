"""Path validation for project documents."""


def valid_note_path(roots, kind, path):
    root = roots.get(kind)
    if root is None or not isinstance(path, str) or not path:
        return False
    target = (root / path).resolve()
    return target.is_relative_to(root.resolve()) and target.is_file() and target.suffix.lower() in ('.md', '.markdown')
