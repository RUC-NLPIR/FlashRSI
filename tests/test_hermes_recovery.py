"""Compare request repair with the pinned original source, then verify state I/O."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.recovery import RecoveryHost

_FIXTURES = Path(__file__).parent / 'fixtures'
_SPEC = importlib.util.spec_from_file_location('hermes_recovery_oracle_driver', _FIXTURES / 'generate_hermes_recovery_upstream.py')
_DRIVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_DRIVER)
_DATA = json.loads((_FIXTURES / 'hermes_recovery_upstream.json').read_text())


@pytest.mark.parametrize('case', _DATA['cases'], ids=lambda case: case['input']['name'])
def test_original_request_repair(case):
    assert _DRIVER.execute(case['input'], native=True) == case['output']


def _host(route=None, state=None):
    route = {'provider':'custom','base_url':'https://fixture.invalid/v1','model_name':'model-a','model_api':'chat_completions','api_key':'fixed-key', **(route or {})}
    engine = SimpleNamespace(config={},_native_disabled=False,_anchor=None,compressor=SimpleNamespace())
    return RecoveryHost(route,engine,lambda event:None,state)


def test_recovery_flags_survive_resume_without_credentials():
    host = _host()
    host._reasoning_effort_rejected = True
    host._reasoning_rejecting_routes[host._route_key] = {'reasoning_content'}
    host._image_rejecting_models.add(('custom','model-a'))
    host._no_list_tool_content_models.add(('custom','model-a'))
    host._fast_mode_unavailable_models.add('model-a')
    host._anthropic_rejected_thinking = (None, {'fixed-fingerprint'})
    state = json.loads(json.dumps(host.snapshot()))
    assert 'fixed-key' not in json.dumps(state)
    restored = _host(state=state)
    assert restored.snapshot() == state
    assert restored.reasoning_for_wire({'enabled':True,'effort':'high'}) is None
    restored.bind_route({**restored.route,'model_name':'model-b'})
    assert restored.reasoning_for_wire({'enabled':True,'effort':'high'}) == {'enabled':True,'effort':'high'}
    restored.bind_route({**restored.route,'model_name':'model-a'})
    assert restored.reasoning_for_wire({'enabled':True,'effort':'high'}) is None


def test_model_rejection_does_not_rewrite_durable_images():
    host = _host()
    host._image_rejecting_models.add(('custom','model-a'))
    durable = [{'role':'user','content':[{'type':'text','text':'Inspect.'},{'type':'image_url','image_url':{'url':'https://fixture.invalid/one.png'}}]}]
    before = copy.deepcopy(durable)
    payload = {'messages':copy.deepcopy(durable)}
    host.begin(durable,payload,'').prepare()
    assert durable == before
    assert payload['messages'][0]['content'] == [{'type':'text','text':'Inspect.'}]


def test_native_compaction_false_string_is_false():
    host = _host()
    host.engine.config['codex_responses_native'] = 'false'
    host.bind_route(host.route)
    assert host.codex_responses_native_compaction is False
