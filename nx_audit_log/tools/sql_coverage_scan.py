#!/usr/bin/env python3
"""Inventory of direct SQL writes that bypass the ORM (and therefore the
generic audit hooks). Re-run after every Odoo upgrade:

    python3 sql_coverage_scan.py /path/to/odoo/addons account stock mail > COVERAGE_SCAN.md
"""
import ast
import os
import re
import sys

WRITE_RE = re.compile(r'^\s*(?:WITH\b.*?\)\s*)?(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"?([a-z_0-9]+|%s)', re.I | re.S)


def literal_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in node.values)
    if isinstance(node, ast.Call):  # SQL("...", ...)
        return literal_text(node.args[0]) if node.args else ''
    if isinstance(node, ast.BinOp):
        return literal_text(node.left)
    return ''


def scan_file(path):
    tree = ast.parse(open(path, encoding='utf-8').read(), path)
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        variables = {}
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                text = literal_text(node.value)
                if text:
                    variables[node.targets[0].id] = text
        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ('execute', 'execute_query', 'execute_query_dict') or not node.args:
                continue
            arg = node.args[0]
            text = variables.get(arg.id, '') if isinstance(arg, ast.Name) else literal_text(arg)
            match = WRITE_RE.search(text)
            if match:
                found.append((func.name, node.lineno, match.group(1).split()[0].upper(), match.group(2)))
    return found


def main(root, modules):
    print('| Module | File | Function | Line | Statement | Table |')
    print('|---|---|---|---|---|---|')
    for module in modules:
        base = os.path.join(root, module)
        for folder, _dirs, files in os.walk(base):
            if '/tests' in folder or '/migrations' in folder:
                continue
            for name in sorted(files):
                if name.endswith('.py'):
                    path = os.path.join(folder, name)
                    for func, line, kind, table in scan_file(path):
                        print(f'| {module} | {os.path.relpath(path, base)} | `{func}` | {line} | {kind} | `{table}` |')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
