"""Tests for nflasher.backend — no real device required."""

import pytest
from unittest.mock import patch, MagicMock
from nflasher.backend import (
    DeviceManager, FlashEngine, FlashOptions, FlashPartition,
    FlashBackend, DeviceState, DeviceInfo,
    detect_backend, backend_version,
)


class TestDetectBackend:
    def test_returns_nphonecli_when_available(self):
        with patch("shutil.which", side_effect=lambda x: "/usr/bin/nphonecli" if x == "nphonecli" else None):
            assert detect_backend() == FlashBackend.NPHONECLI

    def test_falls_back_to_odin4(self):
        def which(x):
            return "/usr/bin/odin4" if x == "odin4" else None
        with patch("shutil.which", side_effect=which):
            assert detect_backend() == FlashBackend.ODIN4

    def test_falls_back_to_heimdall(self):
        def which(x):
            return "/usr/bin/heimdall" if x == "heimdall" else None
        with patch("shutil.which", side_effect=which):
            assert detect_backend() == FlashBackend.HEIMDALL


class TestDeviceManager:
    def _mgr(self, backend=FlashBackend.NPHONECLI):
        logs = []
        states = []
        mgr = DeviceManager(
            on_state_change=lambda s, i: states.append((s, i)),
            on_log=lambda m: logs.append(m),
            backend=backend,
        )
        return mgr, logs, states

    def test_initial_state_disconnected(self):
        mgr, *_ = self._mgr()
        assert mgr.state == DeviceState.DISCONNECTED

    def test_probe_nphonecli_returns_none_on_failure(self):
        mgr, logs, _ = self._mgr()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no device")
            result = mgr._probe_nphonecli()
        assert result is None

    def test_probe_nphonecli_parses_json(self):
        mgr, logs, _ = self._mgr()
        import json
        payload = json.dumps({
            "serial": "R58M12345",
            "model": "SM-G991B",
            "product": "star2ltexx",
            "firmware": "G991BXXU5CVK1",
            "imei": "356938035643809",
            "chip": "Exynos 2100",
            "protocol": "ODIN",
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
            info = mgr._probe_nphonecli()
        assert info is not None
        assert info.model == "SM-G991B"
        assert info.serial == "R58M12345"
        assert info.chip == "Exynos 2100"

    def test_probe_nphonecli_text_fallback(self):
        mgr, _, _ = self._mgr()
        text_output = "Model: SM-A525F\nSerial: RZ8N4567\nFirmware: A525FXXU5CWA1"
        with patch("subprocess.run") as mock_run:
            # First call (--json) fails, second (text) succeeds
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr=""),
                MagicMock(returncode=0, stdout=text_output, stderr=""),
            ]
            info = mgr._probe_nphonecli()
        assert info is not None
        assert info.model == "SM-A525F"

    def test_probe_heimdall_detected(self):
        mgr, _, _ = self._mgr(backend=FlashBackend.HEIMDALL)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Device detected", stderr=""
            )
            info = mgr._probe_heimdall()
        assert info is not None
        assert info.protocol == "HEIMDALL"

    def test_probe_timeout_returns_none(self):
        import subprocess
        mgr, _, _ = self._mgr()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nphonecli", 5)):
            result = mgr._probe_nphonecli()
        assert result is None

    def test_probe_file_not_found_returns_none(self):
        mgr, _, _ = self._mgr()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = mgr._probe_nphonecli()
        assert result is None


class TestFlashEngine:
    def _engine(self, backend=FlashBackend.NPHONECLI):
        logs = []
        progress = []
        done = []
        engine = FlashEngine(
            on_log=lambda m: logs.append(m),
            on_progress=lambda p, l="": progress.append((p, l)),
            on_done=lambda ok, msg: done.append((ok, msg)),
            backend=backend,
        )
        return engine, logs, progress, done

    def test_flash_no_partitions_calls_done_false(self):
        engine, logs, _, done = self._engine()
        engine._run_flash([], FlashOptions())
        assert done and done[0][0] is False

    def test_nphonecli_command_construction(self):
        engine, logs, _, _ = self._engine()
        parts = [
            FlashPartition(flag="--bl",  filepath="/tmp/BL.tar.md5"),
            FlashPartition(flag="--ap",  filepath="/tmp/AP.tar.md5"),
        ]
        opts = FlashOptions(reboot=True, t_flash=False)
        with patch.object(engine, "_run_cmd", return_value=True) as mock_cmd:
            engine._flash_nphonecli(parts, opts)
        cmd = mock_cmd.call_args[0][0]
        assert "nphonecli" in cmd
        assert "flash" in cmd
        assert "--bl" in cmd
        assert "/tmp/BL.tar.md5" in cmd

    def test_odin4_flag_mapping(self):
        engine, _, _, _ = self._engine(backend=FlashBackend.ODIN4)
        parts = [FlashPartition(flag="--bl", filepath="/tmp/BL.tar.md5")]
        with patch.object(engine, "_run_cmd", return_value=True) as mock_cmd:
            engine._flash_odin4(parts, FlashOptions())
        cmd = mock_cmd.call_args[0][0]
        assert "-b" in cmd   # odin4 uses -b not --bl

    def test_tflash_option_appended(self):
        engine, _, _, _ = self._engine()
        parts = [FlashPartition(flag="--ap", filepath="/tmp/AP.tar.md5")]
        opts = FlashOptions(t_flash=True)
        with patch.object(engine, "_run_cmd", return_value=True) as mock_cmd:
            engine._flash_nphonecli(parts, opts)
        cmd = mock_cmd.call_args[0][0]
        assert "--tflash" in cmd

    def test_no_reboot_option(self):
        engine, _, _, _ = self._engine()
        parts = [FlashPartition(flag="--ap", filepath="/tmp/AP.tar.md5")]
        opts = FlashOptions(reboot=False)
        with patch.object(engine, "_run_cmd", return_value=True) as mock_cmd:
            engine._flash_nphonecli(parts, opts)
        cmd = mock_cmd.call_args[0][0]
        assert "--no-reboot" in cmd

    def test_abort_sets_event(self):
        engine, _, _, _ = self._engine()
        engine.abort()
        assert engine._abort_event.is_set()


class TestDeviceInfo:
    def test_str_with_full_info(self):
        info = DeviceInfo(
            model="SM-G991B", serial="R58M12345",
            firmware="G991BXXU5CVK1", chip="Exynos 2100"
        )
        s = str(info)
        assert "SM-G991B" in s
        assert "R58M12345" in s
        assert "Exynos 2100" in s

    def test_str_empty_info(self):
        info = DeviceInfo()
        assert str(info) == "Unknown Device"
