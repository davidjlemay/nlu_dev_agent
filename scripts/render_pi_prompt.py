#!/usr/bin/env python3
"""Render .pi/SYSTEM.md from .pi/SYSTEM.md.j2 + jsgf-dialect.json."""
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.dialect import DialectRegistry


def main():
    root = Path(__file__).parent.parent
    dialect = DialectRegistry.from_config(root / 'jsgf-dialect.json')
    env = Environment(
        loader=FileSystemLoader(str(root / '.pi')),
        keep_trailing_newline=True,
    )
    template = env.get_template('SYSTEM.md.j2')
    rendered = template.render(
        engine=dialect.engine,
        functions=dialect.functions,
        allowed_flag_types=dialect.allowed_flag_types,
        reserved_flag_keys=dialect.reserved_flag_keys,
        lhs_flags_enabled=dialect.lhs_flags_enabled,
        capabilities={
            'max_public_rules': dialect.capabilities.max_public_rules,
            'flags': dialect.capabilities.flags,
            'function_map': dialect.capabilities.function_map,
            'allow_parameterized_rules': dialect.capabilities.allow_parameterized_rules,
        },
    )
    out = root / '.pi' / 'SYSTEM.md'
    out.write_text(rendered)
    print(f"Rendered {out}", file=sys.stderr)


if __name__ == '__main__':
    main()
