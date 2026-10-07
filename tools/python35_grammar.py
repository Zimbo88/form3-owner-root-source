"""Host-side target syntax guard, not proof of Python 3.5 runtime behavior."""
import ast


def parse(source):
    tree = ast.parse(source, feature_version=(3, 5))
    # Python 3.14.4 accepted f-strings despite feature_version=(3, 5) in our
    # negative fixture. Keep an explicit AST guard instead of trusting that hint.
    forbidden = ('JoinedStr', 'FormattedValue', 'TemplateStr', 'Interpolation')
    if any(type(node).__name__ in forbidden for node in ast.walk(tree)):
        raise SyntaxError('String interpolation syntax requires a newer target Python')
    return tree
