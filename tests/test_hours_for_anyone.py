"""Quiet hours that are safe to have on for anyone (WP-M15a).

Riley decided the quiet hours are on by default for new people. At 4c61494
three things in the hour's runner (mnemos/life.py) were safe only for him:

- An hour ran ``claude -p`` without ``--setting-sources``, so the person's own
  Claude Code settings and hooks, another Mnemos's among them, loaded into the
  agent's hour. Mnemos's model has run with ``--setting-sources project`` for
  exactly this reason (mnemos/llm.py).
- The two folders Riley's hours read were named in the code, so an hour on
  anyone's machine could read that person's folders of the same names. They
  come from Mnemos's config now (``life.read_dirs``), and there are none until
  it names some.
- The budgets were fixed in code, so a host app (Ghost) couldn't give a new
  ghost a gentler cap. Mnemos's config sets them per kind (``life.minutes``,
  ``life.token_ceiling``), a host app sets them for the one hour it runs
  (MNEMOS_HOUR_MINUTES, MNEMOS_HOUR_TOKEN_CEILING), and the defaults stay 60
  and 30 minutes, 400,000 and 200,000 tokens.

And everything an hour writes stays under the HOME it runs with: a host app
runs one with a HOME of its own.

Then, from the review of e3877be: nothing the agent writes configures Claude
Code for its next hour (the studio's settings are moved aside before each
hour, and may not be written); the secrets of the account's own home are
denied when the hour runs under another HOME; and a job installed under
another HOME carries it, so it runs where it was installed.

Every hour here is the real runner waking tests/fake_claude.py, which records
what it was given and never runs Claude, and every scheduler is the suite's
stand-in.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import plistlib
import pwd
import shlex
import sqlite3
import subprocess
import sys
import time

import pytest

from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

SCOPE = {'agent_id': 'claude-code', 'person_id': 'user', 'project_scope': 'global'}
ROOT = Path(__file__).resolve().parents[1]
FAKE_MNEMOS = '/opt/fake/mnemos'


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    folder = tmp_path / 'home'
    (folder / '.mnemos').mkdir(parents=True)
    monkeypatch.setenv('HOME', str(folder))
    monkeypatch.setenv('MNEMOS_LIFE_MNEMOS_BIN', FAKE_MNEMOS)
    monkeypatch.setenv('MNEMOS_CLAUDE_BIN', str(ROOT / 'tests/fake_claude.py'))
    monkeypatch.setenv('FAKE_CLAUDE_LOG', str(tmp_path / 'fake.json'))
    monkeypatch.setenv('FAKE_CLAUDE_SCENARIO', 'ok')
    # The executable fake uses env python3 and must use this suite's interpreter.
    monkeypatch.setenv('PATH', str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'])
    for name in ('MNEMOS_HOUR_MINUTES', 'MNEMOS_HOUR_TOKEN_CEILING', 'MNEMOS_HOUR_MODEL'):
        monkeypatch.delenv(name, raising=False)
    return folder


@pytest.fixture
def db(home):
    path = home / '.mnemos/claude-code.db'
    EngramStore(path).close()
    return path


def configure(home, **life):
    """Mnemos's own config, under the HOME the hour runs with."""
    (home / '.mnemos/config.json').write_text(json.dumps({'life': life}))


def work(db):
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture('The ferry timetable changed.', signed_as='claude-opus-5-5',
                        impact='Read the new timetable.')
        runtime.handoff('Check the ferry timetable next session.', signed_as='claude-opus-5-5')
    finally:
        runtime.close()


def run(db, kind='mine', **kwargs):
    from mnemos.life import run_hour
    return run_hour(kind, db_path=str(db), **SCOPE, **kwargs)


def given(tmp_path) -> list[str]:
    """The arguments the fake claude was started with."""
    return json.loads((tmp_path / 'fake.json').read_text())['argv']


def hour_folder(home, record) -> Path:
    return home / '.mnemos/hours/claude-code' / record['id']


def added_dirs(argv) -> list[str]:
    return [argv[index + 1] for index, arg in enumerate(argv) if arg == '--add-dir']


# ── 1. An hour never loads the person's own Claude Code settings ──


@pytest.mark.parametrize('kind', ['mine', 'ours'])
def test_an_hour_loads_none_of_the_persons_own_claude_code_settings(db, home, tmp_path, kind):
    if kind == 'ours':
        work(db)
    record = run(db, kind)

    assert record['status'] == 'done', record['reason']
    argv = given(tmp_path)
    folder = hour_folder(home, record)
    # Only the project's settings (the studio's) load from where Claude Code
    # looks; the hour's own come from its own files.
    assert argv[argv.index('--setting-sources') + 1] == 'project'
    assert argv[argv.index('--settings') + 1] == str(folder / 'settings.json')
    assert '--strict-mcp-config' in argv
    assert argv[argv.index('--mcp-config') + 1] == str(folder / 'mcp.json')
    # The wake still comes from Mnemos itself: its own hook, in its own file.
    settings = json.loads((folder / 'settings.json').read_text())
    [command] = [hook['command'] for entry in settings['hooks']['SessionStart']
                 for hook in entry['hooks']]
    assert command.startswith(f'{FAKE_MNEMOS} hook session-start ')
    # And the dry run says what the hour would run.
    out = io.StringIO()
    run(db, kind, dry_run=True, out=out)
    assert ' --setting-sources project ' in out.getvalue()


# ── 2. The folders an hour may read come from Mnemos's config ──


def test_an_hour_reads_no_folder_the_config_does_not_name(db, home, tmp_path):
    from mnemos import life

    # The two folders Riley's hours read, there on this machine too.
    for name in ('Documents/Repositories', 'Documents/Luca-Design-Artifacts'):
        (home / name).mkdir(parents=True)

    record = run(db)

    assert record['status'] == 'done', record['reason']
    argv = given(tmp_path)
    assert added_dirs(argv) == []
    deny = json.loads((hour_folder(home, record) / 'settings.json').read_text())['permissions']['deny']
    # (Claude Code's settings in the studio may not be written either: section 5.)
    assert [rule for rule in deny if rule.startswith('Edit(') and not rule.endswith('/.claude/**)')] == []
    assert not hasattr(life, 'READ_DIRS')


def test_the_folders_an_hour_reads_are_the_ones_the_config_names(db, home, tmp_path):
    shared = tmp_path / 'shared work'  # absolute, and outside HOME
    shared.mkdir()
    (home / 'Documents/Repositories').mkdir(parents=True)
    (home / 'notes').mkdir()
    (home / 'Documents/Luca-Design-Artifacts').mkdir(parents=True)  # not named
    configure(home, read_dirs=[
        'Documents/Repositories', str(shared), '~/notes', 'not here', '',
        'Documents/Repositories',
    ])

    record = run(db)

    folders = [str(home / 'Documents/Repositories'), str(shared), str(home / 'notes')]
    assert added_dirs(given(tmp_path)) == folders
    deny = json.loads((hour_folder(home, record) / 'settings.json').read_text())['permissions']['deny']
    # Each may be read, and none written.
    assert [rule for rule in deny if rule.startswith('Edit(') and not rule.endswith('/.claude/**)')] == [
        f'Edit(/{f}/**)' for f in folders]


@pytest.mark.parametrize('named', ['Documents/Repositories', {'mine': 'Documents/Repositories'}, 7])
def test_a_read_dirs_that_isnt_a_list_names_no_folder(db, home, tmp_path, named):
    (home / 'Documents/Repositories').mkdir(parents=True)
    configure(home, read_dirs=named)

    run(db)

    assert added_dirs(given(tmp_path)) == []


# ── 3. The budgets can be set, and their defaults stay ──


@pytest.fixture
def budgets(monkeypatch):
    """What each hour was given to spend, (seconds, tokens), as the runner
    hands them to the process it watches."""
    from mnemos import life

    seen = []
    watch = life._watch

    def watching(cmd, studio, env, folder, prompt, max_seconds, max_tokens, *rest, **named):
        seen.append((max_seconds, max_tokens))
        return watch(cmd, studio, env, folder, prompt, max_seconds, max_tokens, *rest, **named)

    monkeypatch.setattr(life, '_watch', watching)
    return seen


def test_the_budgets_keep_their_defaults(db, budgets):
    work(db)
    run(db, 'mine')
    run(db, 'ours')

    assert budgets == [(60 * 60, 400_000), (30 * 60, 200_000)]


def test_mnemoss_config_sets_each_kinds_budget(db, home, budgets):
    configure(home, minutes={'mine': 20, 'ours': 7.5},
              token_ceiling={'mine': 90_000, 'ours': '40000'})
    work(db)
    run(db, 'mine')
    run(db, 'ours')

    assert budgets == [(20 * 60, 90_000), (7.5 * 60, 40_000)]


def test_a_kind_the_config_leaves_out_keeps_its_default(db, home, budgets):
    configure(home, minutes={'mine': 20}, token_ceiling={'ours': 40_000})
    work(db)
    run(db, 'mine')
    run(db, 'ours')

    assert budgets == [(20 * 60, 400_000), (30 * 60, 40_000)]


def test_a_host_apps_budget_for_its_hour_wins_over_the_config(db, home, budgets, monkeypatch):
    configure(home, minutes={'mine': 20}, token_ceiling={'mine': 90_000})
    monkeypatch.setenv('MNEMOS_HOUR_MINUTES', '5')
    monkeypatch.setenv('MNEMOS_HOUR_TOKEN_CEILING', '30000')

    run(db)

    assert budgets == [(5 * 60, 30_000)]


def test_what_the_caller_passes_still_wins(db, home, budgets, monkeypatch):
    configure(home, minutes={'mine': 20}, token_ceiling={'mine': 90_000})
    monkeypatch.setenv('MNEMOS_HOUR_MINUTES', '5')
    monkeypatch.setenv('MNEMOS_HOUR_TOKEN_CEILING', '30000')

    run(db, max_minutes=2, max_tokens=1_000)

    assert budgets == [(2 * 60, 1_000)]


def test_a_host_apps_ceiling_stops_its_hour(db, monkeypatch):
    monkeypatch.setenv('FAKE_CLAUDE_SCENARIO', 'tokens')
    monkeypatch.setenv('MNEMOS_HOUR_TOKEN_CEILING', '500')
    start = time.monotonic()

    record = run(db)

    assert time.monotonic() - start < 20
    assert record['status'] == 'done'
    assert record['reason'] == 'Stopped at the token ceiling (500).'


def test_a_host_apps_minutes_stop_its_hour(db, monkeypatch):
    monkeypatch.setenv('FAKE_CLAUDE_SCENARIO', 'sleep')
    monkeypatch.setenv('MNEMOS_HOUR_MINUTES', '0.05')
    start = time.monotonic()

    record = run(db)

    assert time.monotonic() - start < 20
    assert record['status'] == 'done'
    assert record['reason'] == 'Stopped at the time limit (0.05 minutes).'


@pytest.mark.parametrize('setting, value, reason', [
    ('MNEMOS_HOUR_MINUTES', 'an hour',
     "MNEMOS_HOUR_MINUTES needs a number of minutes above zero, not 'an hour'."),
    ('MNEMOS_HOUR_MINUTES', '-5',
     "MNEMOS_HOUR_MINUTES needs a number of minutes above zero, not '-5'."),
    ('MNEMOS_HOUR_TOKEN_CEILING', '0',
     "MNEMOS_HOUR_TOKEN_CEILING needs a whole number of tokens above zero, not '0'."),
    ('MNEMOS_HOUR_TOKEN_CEILING', '2.5',
     "MNEMOS_HOUR_TOKEN_CEILING needs a whole number of tokens above zero, not '2.5'."),
])
def test_a_host_budget_that_isnt_one_runs_no_hour(db, home, tmp_path, monkeypatch, setting, value, reason):
    monkeypatch.setenv(setting, value)

    record = run(db)

    assert record['status'] == 'failed'
    assert record['reason'] == reason
    assert not (tmp_path / 'fake.json').exists()
    recorded = (home / '.mnemos/hours/claude-code/hours.jsonl').read_text().splitlines()
    assert [json.loads(line)['reason'] for line in recorded] == [reason]
    assert run(db, dry_run=True, out=io.StringIO()) == {'status': 'failed', 'reason': reason}


@pytest.mark.parametrize('life, reason', [
    ({'minutes': {'mine': 0}},
     "life.minutes.mine in Mnemos's config needs a number of minutes above zero, not 0."),
    ({'minutes': {'mine': True}},
     "life.minutes.mine in Mnemos's config needs a number of minutes above zero, not True."),
    ({'token_ceiling': {'mine': 'lots'}},
     "life.token_ceiling.mine in Mnemos's config needs a whole number of tokens above zero, not 'lots'."),
])
def test_a_config_budget_that_isnt_one_runs_no_hour(db, home, tmp_path, life, reason):
    configure(home, **life)

    record = run(db)

    assert record['status'] == 'failed'
    assert record['reason'] == reason
    assert not (tmp_path / 'fake.json').exists()


# ── 4. Everything an hour writes stays under the HOME it runs with ──


def _files(root: Path, *, outside: Path) -> dict[Path, tuple]:
    """Every file and folder under ``root`` but not under ``outside``, with
    its size and when it last changed."""
    seen = {}
    for path in root.rglob('*'):
        if path == outside or outside in path.parents:
            continue
        info = path.stat()
        seen[path] = ('dir',) if path.is_dir() else (info.st_size, info.st_mtime_ns)
    return seen


def test_everything_an_hour_writes_stays_under_the_home_it_runs_with(tmp_path):
    """A host app runs an hour with a HOME of its own (Ghost's test copy:
    …/Ghost Test/Home), from a folder of its own: the hour's record, its
    folder, the studio and what Claude said all land under that HOME, and
    nothing anywhere else."""
    host_home = tmp_path / 'Ghost Test' / 'Home'
    (host_home / '.mnemos').mkdir(parents=True)
    store = host_home / '.mnemos' / 'claude-code.db'
    EngramStore(store).close()
    host_folder = tmp_path / 'Ghost.app working folder'
    host_folder.mkdir()
    fake_log = tmp_path / 'fake.json'  # the fake's record of what it was given
    before = _files(tmp_path, outside=host_home)
    env = {
        **os.environ,
        'HOME': str(host_home),
        'PYTHONPATH': os.pathsep.join([str(ROOT), os.environ.get('PYTHONPATH', '')]),
        'PYTHONDONTWRITEBYTECODE': '1',
    }

    done = subprocess.run(
        [sys.executable, '-m', 'mnemos.cli', 'life', '--hour', 'mine', '--agent-id', 'claude-code',
         '--config-dir', '~/.claude-ghost'],
        cwd=host_folder, env=env, capture_output=True, text=True, timeout=60,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    after = _files(tmp_path, outside=host_home)
    assert {path for path in after if before.get(path) != after[path]} == {fake_log}
    hours = host_home / '.mnemos/hours/claude-code'
    [record] = [json.loads(line) for line in (hours / 'hours.jsonl').read_text().splitlines()]
    assert record['status'] == 'done', record['reason']
    folder = hours / record['id']
    for name in ('prompt.md', 'mcp.json', 'settings.json', 'stderr.txt', 'stream.jsonl'):
        assert (folder / name).is_file(), name
    assert (host_home / '.mnemos/studio/claude-code/worktrees').is_dir()
    assert f"Record: {hours / 'hours.jsonl'}" in done.stdout
    # It woke into the memory under that HOME, and wrote there.
    conn = sqlite3.connect(f'file:{store}?mode=ro', uri=True)
    try:
        written = [row[0] for row in conn.execute('SELECT id FROM journal_entries')]
    finally:
        conn.close()
    assert written == record['journal_ids'] != []
    # The paths it handed Claude are under that HOME: the store, the login it
    # pays with, its studio. The secrets it may not read are that HOME's, and
    # the account's own home's too, which isn't this HOME.
    fake = json.loads(fake_log.read_text())
    assert fake['env_config'] == str(host_home / '.claude-ghost')
    assert os.path.realpath(fake['cwd']) == os.path.realpath(host_home / '.mnemos/studio/claude-code')
    mcp = json.loads((folder / 'mcp.json').read_text())['mcpServers']['mnemos']['args']
    assert mcp[mcp.index('--db-path') + 1] == str(store)
    from mnemos.life import SECRET_PATHS
    account = Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert account != host_home
    deny = json.loads((folder / 'settings.json').read_text())['permissions']['deny']
    secrets = [rule for rule in deny if rule.startswith('Read(/') and '**/.env' not in rule]
    assert secrets == [f'Read(/{base / name}{tail})' for name in SECRET_PATHS
                       for base in (host_home, account) for tail in ('', '/**')]


# ── 5. Nothing the agent writes configures Claude Code for its next hour ──


def test_settings_in_the_studio_are_set_aside_before_the_hour_starts(db, home, tmp_path):
    """The hour's working folder is its studio, where the agent writes, and
    Claude Code loads a project's settings from there: a hook planted in one
    hour would run, outside the sandbox, at the start of the next."""
    from mnemos import life

    studio = life.studio_dir('claude-code')
    (studio / '.claude').mkdir(parents=True)
    planted = {
        'settings.json': json.dumps({'hooks': {'SessionStart': [{'matcher': '*', 'hooks': [
            {'type': 'command', 'command': 'echo planted'}]}]}}),
        'settings.local.json': json.dumps({'env': {'PLANTED': '1'}}),
    }
    def plant():
        for name, text in planted.items():
            (studio / '.claude' / name).write_text(text)

    plant()
    record = run(db)

    assert record['status'] == 'done', record['reason']
    fake = json.loads((tmp_path / 'fake.json').read_text())
    assert os.path.realpath(fake['cwd']) == os.path.realpath(studio)
    assert fake['project_settings'] == [], 'Claude started with the planted settings there'
    assert record['set_aside'] == [str(studio / '.claude' / name) for name in planted]
    folder = hour_folder(home, record)
    for name, text in planted.items():
        assert not (studio / '.claude' / name).exists()
        assert (folder / 'set-aside' / name).read_text() == text
    last = (folder.parent / 'hours.jsonl').read_text().splitlines()[-1]
    assert json.loads(last)['set_aside'] == record['set_aside']
    # The dry run says what the next hour would set aside, and moves nothing.
    plant()
    out = io.StringIO()
    run(db, dry_run=True, out=out)
    assert f"Set aside before the hour, into its folder: {studio / '.claude/settings.json'}" in out.getvalue()
    assert (studio / '.claude/settings.json').exists()


def test_a_linked_claude_folder_is_set_aside_as_the_link(db, home, tmp_path):
    """A ``.claude`` in the studio that links elsewhere (to the person's own
    ~/.claude, say) would load what it points at: the link is moved aside,
    and what it points at is never touched."""
    from mnemos import life

    elsewhere = tmp_path / "the person's own .claude"
    elsewhere.mkdir()
    (elsewhere / 'settings.json').write_text('{"hooks": {}}')
    studio = life.studio_dir('claude-code')
    studio.mkdir(parents=True)
    (studio / '.claude').symlink_to(elsewhere, target_is_directory=True)

    record = run(db)

    assert record['status'] == 'done', record['reason']
    assert json.loads((tmp_path / 'fake.json').read_text())['project_settings'] == []
    assert record['set_aside'] == [str(studio / '.claude')]
    moved = hour_folder(home, record) / 'set-aside' / '.claude'
    assert moved.is_symlink() and os.readlink(moved) == str(elsewhere)
    assert not os.path.lexists(studio / '.claude')
    assert (elsewhere / 'settings.json').read_text() == '{"hooks": {}}'


def test_the_hour_may_not_write_claude_codes_settings_where_an_hour_finds_them(db, home, tmp_path):
    from mnemos import life

    (home / 'Documents/Repositories').mkdir(parents=True)
    configure(home, read_dirs=['Documents/Repositories'])

    record = run(db)

    deny = json.loads((hour_folder(home, record) / 'settings.json').read_text())['permissions']['deny']
    for folder in (life.studio_dir('claude-code'), home / 'Documents/Repositories'):
        assert f'Edit(/{folder}/.claude/**)' in deny


# ── 6. The secrets of the account's own home are denied too ──


def test_an_hour_under_another_home_denies_the_secrets_of_both(db, home, tmp_path, monkeypatch):
    from mnemos import life
    from mnemos.setup import scheduler

    account = tmp_path / "the account's own home"
    monkeypatch.setattr(scheduler, 'account_home', lambda: account)

    record = run(db)

    deny = json.loads((hour_folder(home, record) / 'settings.json').read_text())['permissions']['deny']
    for base in (home, account):
        for name in life.SECRET_PATHS:
            path = base / name
            assert deny.index(f'Read(/{path}/**)') == deny.index(f'Read(/{path})') + 1


def test_an_hour_in_the_accounts_own_home_denies_its_secrets_once(db, home):
    from mnemos import life

    record = run(db)

    deny = json.loads((hour_folder(home, record) / 'settings.json').read_text())['permissions']['deny']
    secrets = [rule for rule in deny if rule.startswith('Read(/') and '**/.env' not in rule]
    assert secrets == [f'Read(/{home / name}{tail})' for name in life.SECRET_PATHS for tail in ('', '/**')]


# ── 7. A job installed under another HOME runs there, and is found there ──


SCHEDULE_SCOPE = ['--agent-id', 'nova', '--person-id', 'riley', '--project-scope', 'demo']
JOB_NAMES = ('maintain', 'maintain-deep', 'hour-mine', 'hour-ours')


def _job(name):
    from mnemos.setup import scheduler

    return next(job for job in (*scheduler.JOBS, *scheduler.HOUR_JOBS) if job.name == name)


@pytest.mark.parametrize('backend', ['launchd', 'systemd', 'crontab'])
def test_a_job_installed_under_another_home_runs_there_and_is_found_there(
    home, tmp_path, monkeypatch, os_scheduler, backend,
):
    """Every scheduler here is the suite's stand-in (tests/conftest.py)."""
    from mnemos.cli import main
    from mnemos.setup import scheduler

    monkeypatch.setattr(scheduler, 'detect_backend', lambda system=None: backend)
    monkeypatch.setattr(scheduler, 'account_home', lambda: tmp_path / "the account's own home")

    assert main(['daemon', 'install', *SCHEDULE_SCOPE, '--hours', '--write']) == 0

    for name in JOB_NAMES:
        if backend == 'launchd':
            job = plistlib.loads(scheduler.launchd_plist_path('nova', _job(name)).read_bytes())
            assert job['EnvironmentVariables']['HOME'] == str(home), name
        elif backend == 'systemd':
            service = scheduler.systemd_unit_dir() / scheduler.systemd_unit_names('nova', _job(name))[0]
            assert f'Environment={scheduler._systemd_value(f"HOME={home}")}' in service.read_text(), name
        else:
            [line] = [line for line in os_scheduler.crontab.splitlines()
                      if scheduler.cron_marks(line, 'nova', name)]
            assert f'HOME={shlex.quote(str(home))} ' in line, name

    assert main(['daemon', 'uninstall', *SCHEDULE_SCOPE, '--write']) == 0

    if backend == 'launchd':
        assert not list((home / 'Library/LaunchAgents').glob('*.plist'))
        assert os_scheduler.loaded == set()
    elif backend == 'systemd':
        assert not list(scheduler.systemd_unit_dir().glob('mnemos-nova-*'))
        assert os_scheduler.enabled == set()
    else:
        assert not any(scheduler.cron_has(os_scheduler.crontab, 'nova', name) for name in JOB_NAMES)


def test_a_job_installed_under_the_accounts_own_home_carries_no_home(home, monkeypatch, os_scheduler):
    from mnemos.cli import main
    from mnemos.setup import scheduler

    monkeypatch.setattr(scheduler, 'detect_backend', lambda system=None: 'launchd')

    assert main(['daemon', 'install', *SCHEDULE_SCOPE, '--hours', '--write']) == 0

    for name in JOB_NAMES:
        job = plistlib.loads(scheduler.launchd_plist_path('nova', _job(name)).read_bytes())
        assert 'HOME' not in job.get('EnvironmentVariables', {}), name
