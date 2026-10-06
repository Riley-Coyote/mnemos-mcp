"""Background maintenance scheduled by the OS, not by OpenClaw.

These jobs run unattended, on someone else's machine, forever. Nobody
reads their logs. A job that installs cleanly and then fails on every
invocation is indistinguishable from one that works, so the generation
is asserted directly rather than trusted.
"""

import json
import plistlib
import shlex

import pytest

from mnemos.setup import scheduler


def _seed_home(tmp_path):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True, exist_ok=True)
    return home


class TestJobSelection:
    def test_transcript_indexing_is_never_scheduled(self):
        """Harvesting transcripts is not continuity, and it buries continuity.

        `mnemos index` encodes extracted transcript facts as the agent's own
        memories — general work-recall, which Mnemos is not for. On one live
        install it had written ~7,058 engrams against 13 deliberate captures,
        and a session-start packet spent five of six long-term slots on
        paraphrases of a single harvested fact. Scheduling it by default
        would rebuild that on every user's machine.
        """
        for has_model in (False, True):
            names = {job.name for job in scheduler.jobs_for(has_model=has_model)}
            assert "index" not in names, (
                "transcript indexing must not be scheduled automatically"
            )

    def test_the_deterministic_maintenance_jobs_always_run(self):
        """Continuity upkeep needs no model and must not be gated on one."""
        names = {job.name for job in scheduler.jobs_for(has_model=False)}
        assert {"maintain", "maintain-deep"} <= names

    def test_every_job_has_exactly_one_schedule(self):
        for job in scheduler.JOBS:
            assert (job.interval_seconds is None) != (job.daily_at is None), job.name

    def test_a_job_cannot_declare_two_schedules(self):
        with pytest.raises(ValueError):
            scheduler.SchedulerJob(
                name="bad",
                args=("consolidate",),
                description="",
                interval_seconds=3600,
                daily_at=(3, 0),
            )


class TestCommandGeneration:
    def test_scope_flags_precede_the_subcommand(self):
        """The Mnemos CLI takes scope as *global* options.

        Appending them instead produces a command that installs fine and
        then fails with "unrecognized arguments" on every scheduled run,
        into a log nobody reads. This is the failure this test exists for.
        """
        job = scheduler.JOBS[0]
        argv = scheduler.command_for(
            job,
            mnemos_command="/usr/local/bin/mnemos",
            scope_args=("--agent-id", "nova", "--db-path", "/tmp/nova.db"),
        )

        assert argv[0] == "/usr/local/bin/mnemos"
        subcommand_index = argv.index("consolidate")
        assert argv.index("--agent-id") < subcommand_index
        assert argv.index("--db-path") < subcommand_index

    def test_deep_maintenance_keeps_its_subcommand_flag_after_the_subcommand(self):
        deep = next(j for j in scheduler.JOBS if j.name == "maintain-deep")
        argv = scheduler.command_for(
            deep, mnemos_command="mnemos", scope_args=("--agent-id", "nova")
        )
        assert argv.index("--deep") > argv.index("consolidate")


class TestPathExpansion:
    """Schedulers are not shells.

    resolve_scope returns the default store as the literal string
    "~/.mnemos/<agent>.db". launchd and systemd pass argv through verbatim,
    so an unexpanded tilde makes every scheduled run operate on a phantom
    store relative to its own working directory — and report a perfectly
    healthy cycle over an empty database while real memory is never
    maintained. Found by installing for real and checking whether the run
    actually landed in the store.
    """

    def test_scheduled_commands_carry_an_absolute_database_path(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        import argparse

        from mnemos.cli import _scope_args

        args = argparse.Namespace(
            agent_id="nova", person_id=None, project_scope=None, db_path=None
        )
        emitted = _scope_args(args)

        db_index = emitted.index("--db-path") + 1
        db_path = emitted[db_index]
        assert "~" not in db_path, f"unexpanded path would break a scheduled job: {db_path}"
        assert db_path.startswith("/"), db_path

    def test_the_expanded_path_still_points_at_the_resolved_store(
        self, tmp_path, monkeypatch
    ):
        """Expansion must not quietly change which store is maintained."""
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        import argparse
        from pathlib import Path

        from mnemos.cli import _cli_scope, _scope_args

        args = argparse.Namespace(
            agent_id="nova", person_id=None, project_scope=None, db_path=None
        )
        emitted = _scope_args(args)
        db_path = emitted[emitted.index("--db-path") + 1]

        assert Path(db_path) == Path(_cli_scope(args).db_path).expanduser()


class TestLaunchd:
    def test_interval_job_uses_start_interval(self):
        job = next(j for j in scheduler.JOBS if j.name == "maintain")
        payload = plistlib.loads(
            scheduler.launchd_plist(job, agent_id="nova", mnemos_command="mnemos")
        )

        assert payload["Label"] == "com.mnemos.nova.maintain"
        assert payload["StartInterval"] == 4 * 3600
        assert "StartCalendarInterval" not in payload
        # Maintenance must not fight for resources at login.
        assert payload["RunAtLoad"] is False

    def test_daily_job_uses_a_calendar_interval(self):
        job = next(j for j in scheduler.JOBS if j.name == "maintain-deep")
        payload = plistlib.loads(
            scheduler.launchd_plist(job, agent_id="nova", mnemos_command="mnemos")
        )

        assert payload["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}
        assert "StartInterval" not in payload

    def test_labels_are_namespaced_per_agent(self):
        """Two agents on one machine must not overwrite each other's jobs."""
        job = scheduler.JOBS[0]
        nova = scheduler.launchd_plist_path("nova", job)
        vektor = scheduler.launchd_plist_path("vektor", job)
        assert nova != vektor


class TestSystemd:
    def test_interval_timer_reruns_and_survives_downtime(self):
        job = next(j for j in scheduler.JOBS if j.name == "maintain")
        service, timer = scheduler.systemd_units(
            job, agent_id="nova", mnemos_command="mnemos"
        )

        assert "Type=oneshot" in service
        assert "ExecStart=mnemos" in service
        assert "OnUnitActiveSec=14400s" in timer
        # A laptop asleep at the scheduled time should still consolidate.
        assert "Persistent=true" in timer
        assert "WantedBy=timers.target" in timer

    def test_daily_timer_uses_oncalendar(self):
        job = next(j for j in scheduler.JOBS if j.name == "maintain-deep")
        _service, timer = scheduler.systemd_units(
            job, agent_id="nova", mnemos_command="mnemos"
        )
        assert "OnCalendar=*-*-* 03:00:00" in timer

    def test_execstart_quotes_paths_and_scope_values(self):
        job = scheduler.JOBS[0]
        service, _timer = scheduler.systemd_units(
            job, agent_id="nova", mnemos_command="/Users/Riley Coyote/bin/mnemos",
            scope_args=("--db-path", "/Users/Riley Coyote/Mnemos data/nova.db"),
        )
        line = next(line for line in service.splitlines() if line.startswith("ExecStart="))
        assert shlex.split(line.removeprefix("ExecStart=")) == [
            "/Users/Riley Coyote/bin/mnemos", "--db-path",
            "/Users/Riley Coyote/Mnemos data/nova.db", "consolidate",
        ]


class TestCrontab:
    def test_interval_and_daily_lines(self):
        maintain = next(j for j in scheduler.JOBS if j.name == "maintain")
        deep = next(j for j in scheduler.JOBS if j.name == "maintain-deep")

        assert scheduler.cron_line(
            maintain, agent_id="nova", mnemos_command="mnemos"
        ).startswith("0 */4 * * *")
        assert scheduler.cron_line(
            deep, agent_id="nova", mnemos_command="mnemos"
        ).startswith("0 3 * * *")

    def test_paths_with_spaces_are_shell_quoted(self):
        job = scheduler.JOBS[0]
        line = scheduler.cron_line(
            job, agent_id="nova", mnemos_command="/Users/Riley Coyote/bin/mnemos",
            scope_args=("--db-path", "/Users/Riley Coyote/Mnemos data/nova.db"),
        )
        command = line.split(" >> ", 1)[0].split(" ", 5)[5]
        assert shlex.split(command) == [
            "/Users/Riley Coyote/bin/mnemos", "--db-path",
            "/Users/Riley Coyote/Mnemos data/nova.db", "consolidate",
        ]

    def test_merge_preserves_a_users_own_crontab(self):
        """A user's crontab is theirs; we only remove lines we wrote."""
        existing = "\n".join([
            "0 9 * * * /usr/bin/backup.sh",
            "*/5 * * * * /home/me/poll.sh  # unrelated",
        ])
        new = [scheduler.cron_line(
            scheduler.JOBS[0], agent_id="nova", mnemos_command="mnemos"
        )]

        merged = scheduler.merge_cron_lines(existing, new, "nova")

        assert "/usr/bin/backup.sh" in merged
        assert "/home/me/poll.sh" in merged
        assert scheduler.CRON_MARKER in merged

    def test_reinstall_replaces_rather_than_stacks(self):
        line = scheduler.cron_line(
            scheduler.JOBS[0], agent_id="nova", mnemos_command="mnemos"
        )
        merged = scheduler.merge_cron_lines("", [line], "nova")
        for _ in range(3):
            merged = scheduler.merge_cron_lines(merged, [line], "nova")

        assert merged.count(scheduler.CRON_MARKER) == 1

    def test_another_agents_jobs_are_left_alone(self):
        nova_line = scheduler.cron_line(
            scheduler.JOBS[0], agent_id="nova", mnemos_command="mnemos"
        )
        vektor_line = scheduler.cron_line(
            scheduler.JOBS[0], agent_id="vektor", mnemos_command="mnemos"
        )
        existing = scheduler.merge_cron_lines("", [nova_line], "nova")

        merged = scheduler.merge_cron_lines(existing, [vektor_line], "vektor")

        assert ":nova:" in merged
        assert ":vektor:" in merged

    def test_uninstall_removes_only_our_lines(self):
        line = scheduler.cron_line(
            scheduler.JOBS[0], agent_id="nova", mnemos_command="mnemos"
        )
        existing = scheduler.merge_cron_lines("0 9 * * * /usr/bin/backup.sh", [line], "nova")

        cleared = scheduler.merge_cron_lines(existing, [], "nova")

        assert "/usr/bin/backup.sh" in cleared
        assert scheduler.CRON_MARKER not in cleared


class TestBackendDetection:
    def test_macos_uses_launchd(self):
        assert scheduler.detect_backend("darwin") == "launchd"

    def test_linux_prefers_systemd_then_crontab(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/bin/systemctl")
        assert scheduler.detect_backend("linux") == "systemd"

        monkeypatch.setattr(
            "shutil.which", lambda name: "/bin/crontab" if name == "crontab" else None
        )
        assert scheduler.detect_backend("linux") == "crontab"

        monkeypatch.setattr("shutil.which", lambda name: None)
        assert scheduler.detect_backend("linux") == "unsupported"


class TestTccWarning:
    """macOS blocks scheduled jobs from reading ~/Documents and friends.

    The same command works by hand and fails on every scheduled run with a
    permission error, into a log file. Found by actually installing and
    kickstarting a job rather than by reading the code.
    """

    def test_warns_for_a_protected_install_location(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        protected = tmp_path / "Documents" / "repo" / ".venv" / "bin" / "mnemos"
        protected.parent.mkdir(parents=True)
        protected.touch()

        warning = scheduler.tcc_warning(str(protected), backend="launchd")

        assert warning is not None
        assert "Documents" in warning

    def test_silent_for_a_normal_install_location(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert scheduler.tcc_warning("/opt/homebrew/bin/mnemos", backend="launchd") is None

    def test_only_applies_to_launchd(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        protected = tmp_path / "Documents" / "bin" / "mnemos"
        protected.parent.mkdir(parents=True)
        protected.touch()
        assert scheduler.tcc_warning(str(protected), backend="systemd") is None


class TestPlan:
    def test_plan_describes_without_touching_the_system(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))

        blueprint = scheduler.plan(
            agent_id="nova",
            mnemos_command="/usr/local/bin/mnemos",
            scope_args=("--agent-id", "nova"),
            has_model=False,
            backend="launchd",
        )

        assert blueprint["backend"] == "launchd"
        assert {e["job"].name for e in blueprint["entries"]} == {
            "maintain", "maintain-deep",
        }
        assert blueprint["skipped"] == []
        for entry in blueprint["entries"]:
            assert not entry["path"].exists(), "plan() must not create anything"


class TestDaemonCli:
    def test_dry_run_schedules_nothing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        from mnemos.cli import main

        assert main(["daemon", "install", "--agent-id", "nova"]) == 0
        out = capsys.readouterr().out
        assert "preview" in out.lower()
        assert not (tmp_path / "home" / "Library" / "LaunchAgents").exists()

    def test_status_reports_when_nothing_is_scheduled(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        from mnemos.cli import main

        assert main(["daemon", "status", "--agent-id", "nova"]) == 0
        out = capsys.readouterr().out
        assert "not scheduled" in out
        assert "mnemos daemon install --write" in out

    def test_activation_failure_is_reported_as_failure(self, tmp_path, monkeypatch, capsys):
        from mnemos.cli import _daemon_install

        blueprint = scheduler.plan(
            agent_id="nova", mnemos_command="mnemos", backend="launchd",
        )
        for entry in blueprint["entries"]:
            entry["path"] = tmp_path / f"{entry['job'].name}.plist"
        monkeypatch.setattr(
            "mnemos.cli._launchctl",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("denied")),
        )
        assert _daemon_install(blueprint, write=True) == 1
        assert "denied" in capsys.readouterr().err


class TestQuietHours:
    """The quiet hours run `mnemos life` with no shell around them, so
    everything a shell would have given them is written into the job: where
    the claude command is, where Mnemos is, a PATH holding claude's folder,
    and a working folder outside the ones macOS keeps from background jobs."""

    CLAUDE = "/Users/me/.local/bin/claude"
    MNEMOS = "/opt/mnemos/bin/mnemos"

    def _env(self, **extra):
        return scheduler.hour_environment(
            claude_bin=self.CLAUDE, mnemos_command=self.MNEMOS, **extra
        )

    def test_mine_at_eight_and_ours_at_seven_by_default(self):
        mine, ours = scheduler.hour_jobs()
        assert (mine.name, mine.args, mine.daily_at) == ("hour-mine", ("life", "--hour", "mine"), (8, 0))
        assert (ours.name, ours.args, ours.daily_at) == ("hour-ours", ("life", "--hour", "ours"), (19, 0))
        moved = scheduler.hour_jobs(mine_at=(6, 45), ours_at=(21, 5))
        assert [job.daily_at for job in moved] == [(6, 45), (21, 5)]

    def test_neither_is_upkeep_or_scheduled_by_default(self):
        names = {job.name for job in scheduler.jobs_for(has_model=True)}
        assert not names & {"hour-mine", "hour-ours"}

    def test_the_environment_finds_claude_and_mnemos_without_a_shell(self):
        env = self._env()
        assert env["PATH"].split(":")[0] == "/Users/me/.local/bin"
        assert "/usr/bin" in env["PATH"].split(":")
        assert env["MNEMOS_CLAUDE_BIN"] == self.CLAUDE
        assert env["MNEMOS_LIFE_MNEMOS_BIN"] == self.MNEMOS
        assert "CLAUDE_CONFIG_DIR" not in env
        assert self._env(config_dir="/Users/me/.claude-2")["CLAUDE_CONFIG_DIR"] == "/Users/me/.claude-2"

    def test_launchd_carries_the_environment_and_the_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        mine = scheduler.hour_jobs()[0]
        payload = plistlib.loads(scheduler.launchd_plist(
            mine, agent_id="nova", mnemos_command=self.MNEMOS,
            scope_args=("--agent-id", "nova"), environment=self._env(),
            working_dir=scheduler.working_directory(),
        ))
        assert payload["ProgramArguments"] == [self.MNEMOS, "--agent-id", "nova", "life", "--hour", "mine"]
        assert payload["EnvironmentVariables"] == self._env()
        assert payload["WorkingDirectory"] == str(tmp_path / ".mnemos")
        assert payload["StartCalendarInterval"] == {"Hour": 8, "Minute": 0}

    def test_systemd_carries_the_environment_and_the_folder(self):
        ours = scheduler.hour_jobs()[1]
        service, timer = scheduler.systemd_units(
            ours, agent_id="nova", mnemos_command=self.MNEMOS,
            environment={**self._env(), "ODD": 'a "quoted" 100%'},
            working_dir="/home/me/.mnemos",
        )
        assert "WorkingDirectory=/home/me/.mnemos" in service
        assert f'Environment="MNEMOS_CLAUDE_BIN={self.CLAUDE}"' in service
        assert 'Environment="ODD=a \\"quoted\\" 100%%"' in service
        assert service.index("Environment=") < service.index("ExecStart=")
        assert "OnCalendar=*-*-* 19:00:00" in timer

    def test_crontab_changes_folder_and_sets_the_environment_for_the_command(self):
        mine = scheduler.hour_jobs()[0]
        line = scheduler.cron_line(
            mine, agent_id="nova", mnemos_command="/Users/Riley Coyote/bin/mnemos",
            environment=self._env(), working_dir="/Users/Riley Coyote/.mnemos",
        )
        assert line.startswith("0 8 * * * cd '/Users/Riley Coyote/.mnemos' && PATH=")
        command = line.split(" && ", 1)[1].split(" >> ", 1)[0]
        words = shlex.split(command)
        assert f"MNEMOS_CLAUDE_BIN={self.CLAUDE}" in words
        assert words[-4:] == ["/Users/Riley Coyote/bin/mnemos", "life", "--hour", "mine"]
        assert scheduler.cron_marks(line, "nova", "hour-mine")

    def test_the_plan_holds_the_hours_whether_or_not_it_schedules_them(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        unready = scheduler.plan(agent_id="nova", mnemos_command=self.MNEMOS, has_model=False,
                                 backend="launchd")
        assert unready["hours_ready"] is False
        assert [entry["job"].name for entry in unready["hours"]] == ["hour-mine", "hour-ours"]
        assert [entry["job"].name for entry in unready["entries"]] == ["maintain", "maintain-deep"]

        ready = scheduler.plan(agent_id="nova", mnemos_command=self.MNEMOS, has_model=False,
                               backend="launchd", hour_env=self._env(),
                               hours=scheduler.hour_jobs(mine_at=(7, 30)))
        assert ready["hours_ready"] is True
        [mine, _ours] = ready["hours"]
        assert plistlib.loads(mine["content"])["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
        assert mine["environment"] == self._env()
        # Upkeep runs in the same folder, and needs nothing else from the environment.
        upkeep = plistlib.loads(ready["entries"][0]["content"])
        assert upkeep["WorkingDirectory"] == str(tmp_path / "home" / ".mnemos")
        assert "EnvironmentVariables" not in upkeep

    def test_an_installed_hours_time_is_read_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        hours = scheduler.hour_jobs(mine_at=(6, 5))
        for backend in ("launchd", "systemd"):
            blueprint = scheduler.plan(agent_id="nova", mnemos_command=self.MNEMOS, has_model=False,
                                       backend=backend, hours=hours, hour_env=self._env())
            mine = blueprint["hours"][0]
            if backend == "launchd":
                mine["path"].parent.mkdir(parents=True, exist_ok=True)
                mine["path"].write_bytes(mine["content"])
            else:
                for path, content in mine["units"].items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
            assert scheduler.installed(blueprint, blueprint["hours"]) == [mine]
            assert scheduler.installed_daily_at(blueprint, mine) == (6, 5)
            assert scheduler.installed_daily_at(blueprint, blueprint["hours"][1]) is None

        blueprint = scheduler.plan(agent_id="nova", mnemos_command=self.MNEMOS, has_model=False,
                                   backend="crontab", hours=hours, hour_env=self._env())
        crontab = blueprint["hours"][0]["line"] + "\n"
        assert scheduler.installed_daily_at(blueprint, blueprint["hours"][0], crontab) == (6, 5)
        assert scheduler.installed(blueprint, blueprint["hours"], crontab) == [blueprint["hours"][0]]


class TestFindingClaude:
    def _claude(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        binary = folder / "claude"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        return binary

    def test_the_one_on_path_as_found_not_followed_through_its_link(self, tmp_path, monkeypatch):
        """Claude Code's installer keeps ~/.local/bin/claude a link to the
        current version, and moves it on update: a job pinned to the version
        behind the link would break when that version is removed."""
        version = self._claude(tmp_path / "versions" / "2.1.0")
        link_dir = tmp_path / "bin"
        link_dir.mkdir()
        (link_dir / "claude").symlink_to(version)
        monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
        monkeypatch.setenv("PATH", str(link_dir))

        assert scheduler.find_claude() == str(link_dir / "claude")

    def test_mnemos_claude_bin_first_and_nothing_when_there_is_none(self, tmp_path, monkeypatch):
        named = self._claude(tmp_path / "named")
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(named))
        assert scheduler.find_claude() == str(named)

        monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(tmp_path / "gone" / "claude"))
        assert scheduler.find_claude() is None
        monkeypatch.delenv("MNEMOS_CLAUDE_BIN")
        assert scheduler.find_claude() is None


class TestCrontabKeepsWhatItDoesNotReplace:
    def _line(self, name, agent="nova"):
        job = next(j for j in (*scheduler.JOBS, *scheduler.HOUR_JOBS, *scheduler.RETIRED_JOBS)
                   if j.name == name)
        return scheduler.cron_line(job, agent_id=agent, mnemos_command="mnemos")

    def test_replacing_names_whole_jobs_only(self):
        existing = "\n".join([
            "0 9 * * * /usr/bin/backup.sh",
            self._line("maintain"), self._line("maintain-deep"), self._line("hour-mine"),
            self._line("index"), self._line("maintain", agent="vega"),
        ])
        merged = scheduler.merge_cron_lines(
            existing, [self._line("maintain")], "nova", replacing=["maintain", "index"],
        )
        assert merged.count(":nova:maintain\n") == 1, "replaced, not stacked"
        assert scheduler.cron_has(merged, "nova", "maintain-deep"), "maintain is not maintain-deep"
        assert scheduler.cron_has(merged, "nova", "hour-mine"), "the quiet hours stay"
        assert not scheduler.cron_has(merged, "nova", "index")
        assert scheduler.cron_has(merged, "vega", "maintain") and "/usr/bin/backup.sh" in merged

    def test_cron_has_reads_whole_names(self):
        crontab = self._line("maintain-deep") + "\n"
        assert scheduler.cron_has(crontab, "nova", "maintain-deep")
        assert not scheduler.cron_has(crontab, "nova", "maintain")


class TestTheIndexerJobIsRetired:
    def test_an_earlier_install_of_it_is_found_to_be_removed(self, tmp_path, monkeypatch):
        """The first `mnemos daemon install` scheduled `mnemos index` every 30
        minutes when a provider was configured. It is retired with the
        indexer, and found where an earlier install left it."""
        monkeypatch.setenv("HOME", str(_seed_home(tmp_path)))
        [index] = [job for job in scheduler.RETIRED_JOBS if job.name == "index"]
        assert index.args == ("index",)

        blueprint = scheduler.plan(agent_id="nova", mnemos_command="mnemos", has_model=True,
                                   backend="launchd")
        plist = scheduler.launchd_plist_path("nova", index)
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"<plist/>")
        assert [entry["job"].name for entry in scheduler.retired_installed(blueprint)] == ["index"]

        blueprint = scheduler.plan(agent_id="nova", mnemos_command="mnemos", has_model=True,
                                   backend="crontab")
        crontab = scheduler.cron_line(index, agent_id="nova", mnemos_command="mnemos")
        assert [entry["job"].name for entry in scheduler.retired_installed(blueprint, crontab)] == ["index"]


class TestTccWarningFindsTheCode:
    """The warning that bit on 2026-10-06: Mnemos installed in place from a
    source checkout under ~/Documents. Its command can live anywhere (a uv
    tool, a venv elsewhere) and still import the checkout, which a
    background job may not read."""

    def test_a_checkout_under_documents_warns_though_the_command_is_elsewhere(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        checkout = tmp_path / "Documents" / "Repositories" / "mnemos" / "mnemos"
        checkout.mkdir(parents=True)

        warning = scheduler.tcc_warning(
            "/opt/homebrew/bin/mnemos", backend="launchd", package_dir=checkout,
        )

        assert warning is not None
        assert "~/Documents/Repositories/mnemos/mnemos" in warning
        assert "background jobs will fail" in warning
        assert "PyPI" in warning and "wheel" in warning

    def test_an_install_outside_those_folders_is_quiet(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        site = tmp_path / ".local" / "pipx" / "venvs" / "mnemos-continuity" / "lib" / "mnemos"
        site.mkdir(parents=True)
        assert scheduler.tcc_warning(
            "/opt/homebrew/bin/mnemos", backend="launchd", package_dir=site,
        ) is None

    def test_by_default_it_looks_at_this_packages_own_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        inside = tmp_path / "Desktop" / "mnemos" / "mnemos"
        inside.mkdir(parents=True)
        monkeypatch.setattr(scheduler, "package_folder", lambda: inside)
        assert "~/Desktop/mnemos/mnemos" in scheduler.tcc_warning("/usr/bin/mnemos", backend="launchd")
        monkeypatch.setattr(scheduler, "package_folder", lambda: tmp_path / "elsewhere")
        assert scheduler.tcc_warning("/usr/bin/mnemos", backend="launchd") is None


class TestTheRealSchedulerCalls:
    """The functions that reach the OS, run against a stand-in for the
    commands they start (the suite's fake replaces them everywhere else)."""

    def test_crontab_reads_and_writes_through_the_crontab_command(self, os_scheduler, monkeypatch):
        import subprocess

        ran = []

        def run(argv, **kwargs):
            ran.append((argv, kwargs.get("input")))
            return subprocess.CompletedProcess(argv, 0, stdout="0 9 * * * backup\n", stderr="")

        monkeypatch.setattr(scheduler.subprocess, "run", run)
        assert os_scheduler.real["read_crontab"]() == "0 9 * * * backup\n"
        assert os_scheduler.real["write_crontab"]("0 9 * * * backup\n") is True
        assert ran == [(["crontab", "-l"], None), (["crontab", "-"], "0 9 * * * backup\n")]

        def missing(argv, **kwargs):
            raise FileNotFoundError(argv[0])

        monkeypatch.setattr(scheduler.subprocess, "run", missing)
        assert os_scheduler.real["read_crontab"]() == ""
        assert os_scheduler.real["write_crontab"]("x\n") is False
        assert os_scheduler.real["launchd_job_active"]("nova", scheduler.JOBS[0]) is False
        assert os_scheduler.real["systemd_timer_active"]("nova", scheduler.JOBS[0]) is False
