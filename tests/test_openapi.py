import os

import pytest

yaml = pytest.importorskip('yaml')

from mylar import api

SPEC = os.path.join(os.path.dirname(__file__), '..', 'docs', 'openapi.yaml')


@pytest.fixture(scope='module')
def spec():
    with open(SPEC) as f:
        return yaml.safe_load(f)


def implemented_commands():
    return {c for c in api.cmd_list if hasattr(api.Api, '_' + c)}


@pytest.mark.unit
def test_every_command_is_in_the_spec(spec):
    listed = {p[len('/api/'):] for p in spec['paths']}
    assert implemented_commands() - listed == set()
    assert listed - implemented_commands() == set()


@pytest.mark.unit
def test_operations_are_named_after_commands(spec):
    for path, item in spec['paths'].items():
        assert item['get']['operationId'] == path[len('/api/'):]
        assert '200' in item['get']['responses']


@pytest.mark.unit
def test_destructive_commands_are_marked(spec):
    for cmd in ('delComic', 'shutdown', 'restart', 'update'):
        assert spec['paths']['/api/' + cmd]['get'].get('x-destructive') is True
