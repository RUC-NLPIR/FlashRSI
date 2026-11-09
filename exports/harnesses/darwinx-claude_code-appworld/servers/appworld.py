"""Run-local stdio MCP bridge; only execute is exposed, never controller grading."""
import asyncio
import ast
import json
from pathlib import Path
import sys


_FORBIDDEN_APIS_MARKER = "Usage of the following module is not allowed: apis"
_APIS_HINT = (
    "[Hint: the `apis` module is already imported in this AppWorld shell. "
    "Do not `import apis` or `from apis import ...`; use `apis.<app>.<api>(...)` "
    "directly and print the result.]"
)


class _ApisImportRewriter(ast.NodeTransformer):
    """Replace ``import apis`` / ``from apis import ...`` with assignments.

    AppWorld injects ``apis`` into the persistent shell and rejects explicit
    imports of that module.  Assignments preserve later references to ``apis``
    or to the imported names without altering unrelated code.
    """

    def __init__(self):
        self.changed = False

    def visit_Import(self, node):
        normal_names = []
        apis_aliases = []
        for alias in node.names:
            if alias.name == 'apis':
                self.changed = True
                apis_aliases.append(alias.asname)
            else:
                normal_names.append(alias)

        statements = []
        if normal_names:
            statements.append(ast.Import(names=normal_names))
        for alias in apis_aliases:
            if alias:
                statements.append(ast.Assign(
                    targets=[ast.Name(id=alias, ctx=ast.Store())],
                    value=ast.Name(id='apis', ctx=ast.Load())))
        if not statements:
            # Keep a valid statement body even when ``import apis`` was the
            # only statement in a block.  ``apis`` then resolves to the
            # injected shell object in the surrounding scope.
            statements.append(ast.Pass())
        return statements

    def visit_ImportFrom(self, node):
        if node.module != 'apis' or node.level != 0:
            return node
        if any(alias.name == '*' for alias in node.names):
            # ``from apis import *`` cannot be mapped safely; leave it intact.
            return node

        self.changed = True
        return [
            ast.Assign(
                targets=[ast.Name(id=alias.asname or alias.name, ctx=ast.Store())],
                value=ast.Attribute(
                    value=ast.Name(id='apis', ctx=ast.Load()),
                    attr=alias.name,
                    ctx=ast.Load()))
            for alias in node.names
        ]


def _rewrite_apis_imports(code):
    """Rewrite disallowed AppWorld ``apis`` imports, or return code unchanged."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    rewriter = _ApisImportRewriter()
    new_tree = rewriter.visit(tree)
    if not rewriter.changed:
        return code
    try:
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)
    except Exception:
        return code


def _augment_forbidden_apis_error(raw):
    """Append a recoverable hint only for the exact forbidden-apis failure.

    The submitted code is never rewritten or re-executed here, and every other
    shell response is returned byte-for-byte unchanged. For the error case
    only, the shell's JSON object is kept valid by appending the hint inside
    its ``output`` field.
    """
    if _FORBIDDEN_APIS_MARKER not in raw:
        return raw
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict) and isinstance(payload.get('output'), str):
            payload['output'] = payload['output'] + '\n' + _APIS_HINT
            return json.dumps(payload)
    except (ValueError, TypeError, AttributeError):
        pass
    return raw + '\n' + _APIS_HINT


async def execute(code):
    socket = json.loads(Path('appworld-connection.json').read_text())['socket']
    reader, writer = await asyncio.open_unix_connection(socket, limit=8 * 1024 * 1024)
    try:
        code = _rewrite_apis_imports(code)
        writer.write((json.dumps({'operation': 'execute', 'code': code}) + '\n').encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request:
            continue
        method = request['method']
        try:
            if method == 'initialize':
                result = {'protocolVersion': request['params']['protocolVersion'],
                          'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'appworld', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [{'name': 'appworld_execute',
                          'description': (
                              'Execute Python in the supplied persistent AppWorld shell. '
                              'The `apis` object is already available: do NOT write `import apis` '
                              'or `from apis import ...`. Call `apis.<app>.<api>(...)` directly '
                              'and always `print()` the result you want returned. '
                              'Discover APIs with `apis.api_docs.show_app_descriptions()`, '
                              '`apis.api_docs.show_api_descriptions(app_name=...)`, and '
                              '`apis.api_docs.show_api_doc(app_name=..., api_name=...)`.' ),
                          'inputSchema': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code'], 'additionalProperties': False}}]}
            elif method == 'tools/call':
                if request['params']['name'] != 'appworld_execute':
                    raise ValueError('Unknown tool')
                output = asyncio.run(execute(request['params']['arguments']['code']))
                output = _augment_forbidden_apis_error(output)
                result = {'content': [{'type': 'text', 'text': output}]}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
                continue
        except Exception as error:
            result = {'content': [{'type': 'text', 'text': str(error)}], 'isError': True}
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)


if __name__ == '__main__':
    main()
