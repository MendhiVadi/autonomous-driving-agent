"""Regression tests for control validation and runtime ownership."""
import io
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from vehicle.control import VehicleCommand
from runtime.watchdog import CommandWatchdog, LinkWatchdog
from vehicle.safety import SafetySupervisor, SafetyLimits
from runtime.gesture import GestureBiasReceiver, policy_bias_from_payload
from agent_drive import command_from_payload
from runtime.archive import install
from stack_supervisor import Supervisor, terminate_tree

class HardeningTests(unittest.TestCase):
    def state(self, **updates):
        values = dict(speed_kmh=10., obstacle_distance_m=80., lane_error_m=0., command_age_s=.01,
                      collision=False, red_light=False)
        values.update(updates)
        return values

    def test_lane_departure_on_either_side_brakes(self):
        for offset in (-2.1, 2.1):
            safe, reasons = SafetySupervisor().apply(VehicleCommand(accelerator=.5), self.state(lane_error_m=offset))
            self.assertEqual((safe.accelerator, safe.brake), (0, 1))
            self.assertIn('lane_departure', reasons)

    def test_missing_or_malformed_telemetry_brakes(self):
        cases = [{}, None, self.state(speed_kmh='10'), self.state(command_age_s=-1),
                 self.state(obstacle_distance_m=-1), self.state(red_light='false'),
                 self.state(lane_error_m=float('nan'))]
        for state in cases:
            with self.subTest(state=state):
                safe, reasons = SafetySupervisor().apply(VehicleCommand(accelerator=.5), state)
                self.assertEqual((safe.accelerator, safe.brake), (0, 1))
                self.assertIn('invalid_telemetry_or_command', reasons)

    def test_clear_valid_state_keeps_bounded_control(self):
        safe, reasons=SafetySupervisor().apply(VehicleCommand(accelerator=.3),self.state())
        self.assertEqual(safe.accelerator,.3)
        self.assertFalse(reasons)

    def test_nan_infinity_and_nonpositive_watchdog_configuration_rejected(self):
        for value in (math.nan, math.inf, -math.inf, 0, -1):
            for factory in (lambda:CommandWatchdog(value), lambda:CommandWatchdog(poll_interval_s=value),
                            lambda:LinkWatchdog(value), lambda:SafetyLimits(stale_command_after_s=value),
                            lambda:GestureBiasReceiver(stale_after_s=value)):
                with self.subTest(value=value), self.assertRaises(ValueError): factory()

    def test_invalid_control_never_becomes_full_throttle(self):
        for field in ('accelerator','brake','clutch','steering_angle_deg','gear'):
            for value in (math.nan,math.inf,-math.inf):
                with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                    command_from_payload({field:value})
        for payload in ([],None,{'hand_brake':'false'},{'accelerator':True},{'gear':1.5},{'unknown':1}):
            with self.assertRaises(ValueError): command_from_payload(payload)

    def test_watchdog_retries_failed_emergency_brake(self):
        delivered=threading.Event()
        calls=[]
        def brake():
            calls.append(1)
            if len(calls)==1: raise RuntimeError('transient RPC failure')
            delivered.set()
        watchdog=CommandWatchdog(.03,.01)
        with self.assertLogs(level='ERROR'):
            watchdog.start(brake)
            watchdog.command_received()
            try: self.assertTrue(delivered.wait(1))
            finally: watchdog.stop()
        self.assertGreaterEqual(len(calls),2)

    def test_gestures_cannot_bind_lan_or_accept_nonobject_tracking(self):
        for host in ('0.0.0.0','10.42.0.2','192.168.1.1'):
            with self.assertRaises(ValueError): GestureBiasReceiver(host=host)
        for payload in (None,[],2,'bad',{'tracking':'false','bias':{'turn_left':.1}}):
            self.assertFalse(policy_bias_from_payload(payload).active)

    def test_startup_never_kills_an_unowned_process(self):
        supervisor=Supervisor([],Path(tempfile.gettempdir()),thermal_guard=False)
        with patch('stack_supervisor.find_orphans',return_value=[987654]), patch('stack_supervisor.terminate_tree') as kill:
            with self.assertRaisesRegex(RuntimeError,'unowned'): supervisor.sweep_orphans()
            kill.assert_not_called()

    def test_tree_termination_reports_failed_system_call(self):
        with patch('stack_supervisor.sys.platform','win32'), patch('stack_supervisor.subprocess.run',return_value=Mock(returncode=1)):
            self.assertFalse(terminate_tree(987654))

    def test_map_archive_rejects_traversal_before_any_write(self):
        for name in ('../outside','CarlaUE4/Content/../../outside','C:/outside','CarlaUE4/Content/NUL.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);archive=root/'maps.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('CarlaUE4/Content/valid.txt','valid')
                    z.writestr(name,'bad')
                with self.assertRaises(ValueError): install(archive,root,True)
                self.assertFalse((root/'CarlaUE4').exists())

    def test_map_archive_extracts_only_validated_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'maps.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('CarlaUE4/Content/Map/a.txt','asset')
                z.writestr('unrelated.txt','do not extract')
            self.assertEqual(install(archive,root,False),1)
            self.assertFalse((root/'CarlaUE4').exists())
            install(archive,root,True)
            self.assertEqual((root/'CarlaUE4/Content/Map/a.txt').read_text(encoding="utf-8"),'asset')
            self.assertFalse((root/'unrelated.txt').exists())


class AdditionalBoundaryTests(unittest.TestCase):
    def test_normalization_rejects_invalid_state(self):
        from learning.contract import normalize_features
        for bad in (math.nan, math.inf, '0', True):
            with self.assertRaises(ValueError): normalize_features([bad]+[0.]*7)

    def test_recovery_rejects_nonfinite_control(self):
        from learning.assistance import (apply_stall_recovery)
        from simulation.observations import (wrap_angle)
        self.assertEqual(apply_stall_recovery([0,0,0,30,80,0,0,1],math.nan,0,6),(0,1,False))
        with self.assertRaises(ValueError): wrap_angle(math.inf)

    def test_recorder_rejects_escaping_name_and_nonfinite_records(self):
        from telemetry.recorder import EpisodeRecorder
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): EpisodeRecorder(directory, '../escape')
            with EpisodeRecorder(directory, 'valid') as recorder:
                with self.assertRaises(ValueError): recorder.record([math.nan], {})
            self.assertEqual(recorder.path.read_text(encoding="utf-8"),'')

    def test_visualizer_rejects_foreign_host_and_origin(self):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from learning.model import (MLP)
        from telemetry.visualizer import NeuralVisualizer
        model=MLP([8,24,16,3])
        visual=NeuralVisualizer(model,'test.json',open_browser=False,save_session=False)
        try:
            for headers,code in (({'Host':'attacker.invalid'},421),({'Origin':'http://attacker.invalid'},403)):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(Request(visual.url+'state',headers=headers),timeout=2)
                self.assertEqual(raised.exception.code,code)
        finally: visual.close()

    def test_runtime_lease_blocks_a_second_session_and_releases(self):
        from runtime.lease import runtime_lease
        errors=[]
        def contender():
            try:
                with runtime_lease(): pass
            except RuntimeError as exc: errors.append(str(exc))
        with runtime_lease():
            thread=threading.Thread(target=contender);thread.start();thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors),1)
        with runtime_lease(): pass


class HardwareGuardTests(unittest.TestCase):
    def test_unreadable_or_malformed_log_blocks_start(self):
        from runtime.health import check_system_health
        for output in (Mock(returncode=1,stdout='[]'),Mock(returncode=0,stdout='bad'),Mock(returncode=0,stdout='')):
            with patch('runtime.health.sys.platform','win32'),patch('runtime.health.subprocess.run',return_value=output):
                self.assertFalse(check_system_health().safe)
        with patch('runtime.health.sys.platform','win32'),patch('runtime.health.subprocess.run',side_effect=OSError('denied')):
            self.assertFalse(check_system_health().safe)

    def test_verified_empty_log_allows_start(self):
        from runtime.health import check_system_health
        with patch('runtime.health.sys.platform','win32'),patch('runtime.health.subprocess.run',return_value=Mock(returncode=0,stdout='[]')):
            self.assertTrue(check_system_health().safe)

    def test_query_window_cannot_hide_a_longer_cooldown(self):
        from runtime.health import check_system_health
        with patch('runtime.health.collect_events',return_value=[]) as query:
            self.assertTrue(check_system_health(window_s=1).safe)
            self.assertGreaterEqual(query.call_args.kwargs['window_s'],3600)
