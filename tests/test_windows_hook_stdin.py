"""Hook stdin is a Windows pipe, not a socket (regression for issue #8).

These subprocess tests deliberately keep one writer open and deliver another
payload late. Reading from an empty pipe must finish within the timeout,
without a background reader thread leaking into later hook invocations.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import suppress

import pytest


_CHILD = """
import json, os, sys, time
from mnemos.cue import stdin_ready, read_payload
mode = sys.argv[1]
print('ready', flush=True)
deadline = time.monotonic() + float(sys.argv[2])
if mode == 'payload':
    data = read_payload(sys.stdin, deadline=deadline)
    print(json.dumps({'payload': data.decode('utf-8')}), flush=True)
else:
    ready = stdin_ready(sys.stdin.fileno(), float(sys.argv[2]))
    data = os.read(sys.stdin.fileno(), 65536) if ready else None
    print(json.dumps({
        'ready': ready,
        'data': data.decode('utf-8') if data is not None else None,
    }), flush=True)
"""


def _pipe_case(*, mode="ready", timeout=0.35, parts=(), close=False):
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, mode, str(timeout)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert child.stdin is not None
    try:
        assert child.stdout.readline().strip() == b'ready'
        for delay, payload in parts:
            time.sleep(delay)
            child.stdin.write(payload)
            child.stdin.flush()
        if close:
            child.stdin.close()
        assert child.wait(timeout=5) == 0, child.stderr.read().decode()
        assert child.stdout is not None
        return json.loads(child.stdout.read().decode())
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        if child.stdin and not child.stdin.closed:
            child.stdin.close()
        if child.stdout:
            child.stdout.close()
        if child.stderr:
            child.stderr.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows anonymous pipe regression")
def test_windows_pipe_is_ready_when_json_arrives():
    data = _pipe_case(parts=[(0, b'{"a":1}')], close=True)
    assert data == {"ready": True, "data": '{"a":1}'}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows anonymous pipe regression")
def test_windows_pipe_open_and_empty_times_out():
    data = _pipe_case(timeout=0.18)
    assert data == {"ready": False, "data": None}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows anonymous pipe regression")
def test_windows_pipe_closed_returns_eof_not_hang():
    data = _pipe_case(close=True)
    assert data == {"ready": True, "data": ""}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows anonymous pipe regression")
def test_windows_pipe_handles_late_payload():
    data = _pipe_case(timeout=0.45, parts=[(0.10, b'{"b":2}')], close=True)
    assert data == {"ready": True, "data": '{"b":2}'}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows anonymous pipe regression")
def test_windows_read_payload_reassembles_json_chunks():
    data = _pipe_case(
        mode="payload", timeout=0.60,
        parts=[(0, b'{"session_id":'), (0.05, b'"late"}')], close=True,
    )
    assert json.loads(data["payload"]) == {"session_id": "late"}


def test_posix_pipe_readiness_still_uses_select():
    if os.name == "nt":
        pytest.skip("Windows pipes tested above")
    from mnemos.cue import stdin_ready

    reader, writer = os.pipe()
    try:
        assert stdin_ready(reader, 0.01) is False
        os.write(writer, b"x")
        assert stdin_ready(reader, 0.01) is True
        assert os.read(reader, 1) == b"x"
    finally:
        os.close(reader)
        os.close(writer)


_HOOK = """
import json, sys
from mnemos import cli, cue
original = cue.read_payload
def read(stream, *, deadline):
    print('ready', flush=True)
    return original(stream, deadline=deadline)
cue.read_payload = read
if sys.argv[1] == 'metadata':
    from mnemos.interface import context_packet
    def packet(store, query, **kw):
        return {'prompt': json.dumps({key: kw[key] for key in
                ('reader_model', 'reader_session', 'workdir')})}
    context_packet.build_context_packet = packet
sys.exit(cli.main(sys.argv[2:]))
"""


def _hook_case(db, which, payload, *, metadata=False):
    """Delay data until the actual CLI reader is waiting, keeping stdin open."""
    child = subprocess.Popen(
        [sys.executable, '-c', _HOOK, 'metadata' if metadata else 'real',
         'hook', which, '--db-path', str(db), '--agent-id', 'pipe-test'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        assert child.stdout.readline().strip() == b'ready'
        time.sleep(0.10)
        child.stdin.write(json.dumps(payload).encode('utf-8'))
        child.stdin.flush()
        assert child.wait(timeout=15) == 0, child.stderr.read().decode()
        out = child.stdout.read()
        assert out, child.stderr.read().decode()
        return json.loads(out)['hookSpecificOutput']
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        for stream in (child.stdin, child.stdout, child.stderr):
            with suppress(OSError):
                stream.close()


def test_session_start_receives_delayed_model_session_and_cwd(tmp_path):
    from mnemos.store.sqlite_store import EngramStore

    db = tmp_path / 'metadata.db'
    EngramStore(str(db)).close()
    payload = {'session_id': 'late-session', 'model': 'gpt-6',
               'cwd': str(tmp_path / 'a folder with spaces')}
    block = _hook_case(db, 'session-start', payload, metadata=True)
    assert block['hookEventName'] == 'SessionStart'
    assert json.loads(block['additionalContext']) == {
        'reader_model': payload['model'], 'reader_session': payload['session_id'],
        'workdir': payload['cwd'],
    }


@pytest.mark.parametrize('which', ['session-start', 'prompt'])
def test_both_hooks_emit_captured_context_from_delayed_pipe(tmp_path, which):
    from mnemos.simple_runtime import MnemosRuntime

    db = tmp_path / 'hooks.db'
    text = 'The lighthouse keeper closes the storm shutters before the fog comes in.'
    runtime = MnemosRuntime(db_path=str(db), agent_id='pipe-test', use_dedicated_model=False)
    try:
        runtime.capture(text, importance='high', signed_as='gpt-6')
        # The words fallback needs distinctive words among other memories.
        for other in ('Riley prefers cold brew', 'Our garden grows tomatoes',
                      'The deployment uses a staging server', 'Read the design document first'):
            runtime.capture(other, signed_as='gpt-6')
    finally:
        runtime.close()
    block = _hook_case(db, which, {
        'session_id': 'hook-' + which, 'model': 'gpt-6', 'cwd': str(tmp_path),
        'hook_event_name': 'SessionStart' if which == 'session-start' else 'UserPromptSubmit',
        'prompt': 'The lighthouse keeper asked whether the storm shutters close tonight in the fog',
    })
    assert text in block['additionalContext']
