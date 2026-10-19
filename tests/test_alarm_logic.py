#!/usr/bin/env python3
"""
Tests for the alarm's decision logic and the push receiver.
Run on the Pi with the venv (it has Flask):
    venv/bin/python -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'core'))
sys.path.insert(0, str(ROOT))

import settings
import statefiles
from alarm_trigger import alarm_action, PIANOBAR_SONG


class AlarmActionTests(unittest.TestCase):
    alarm_at = datetime(2026, 10, 20, 8, 8)
    key = '2026-10-20T14:08:00.000Z'

    def action(self, now, handled=None):
        return alarm_action(now, self.alarm_at, self.key, handled)

    def test_waits_before_alarm_time(self):
        self.assertEqual(self.action(self.alarm_at - timedelta(seconds=1)), 'wait')

    def test_rings_at_alarm_time(self):
        self.assertEqual(self.action(self.alarm_at), 'ring')

    def test_rings_late_within_grace(self):
        self.assertEqual(self.action(self.alarm_at + timedelta(minutes=settings.LATE_GRACE_MINUTES)), 'ring')

    def test_missed_after_grace(self):
        late = self.alarm_at + timedelta(minutes=settings.LATE_GRACE_MINUTES, seconds=1)
        self.assertEqual(self.action(late), 'missed')

    def test_never_rings_twice(self):
        self.assertEqual(self.action(self.alarm_at, handled=self.key), 'wait')

    def test_new_alarm_same_day_still_rings(self):
        # Rang at 08:08; a second alarm the same day has a different nextAlarm
        self.assertEqual(alarm_action(datetime(2026, 10, 20, 14, 0), datetime(2026, 10, 20, 14, 0),
                                      '2026-10-20T20:00:00.000Z', self.key), 'ring')

    def test_no_alarm(self):
        self.assertEqual(alarm_action(datetime.now(), None, None, None), 'wait')


class PianobarOutputTests(unittest.TestCase):
    def test_song_line_counts_as_started(self):
        self.assertTrue(PIANOBAR_SONG.match('|>  "Cheap Thrills" by "Sia" on "This Is Acting"'))

    def test_station_line_does_not(self):
        self.assertFalse(PIANOBAR_SONG.match('|>  Station "Morning Hits Radio" (104370043902517433)'))


class StateFileTests(unittest.TestCase):
    def test_utc_converts_to_local(self):
        utc = '2026-10-20T14:08:00.000Z'
        expected = statefiles.parse_iso(utc).astimezone().replace(tzinfo=None)
        self.assertEqual(statefiles.to_local(utc), expected)

    def test_signals_are_one_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            signal_file = Path(tmp) / 'alarm_stop'
            statefiles.send_signal(signal_file)
            self.assertTrue(statefiles.take_signal(signal_file))
            self.assertFalse(statefiles.take_signal(signal_file))


class PushReceiverTests(unittest.TestCase):
    def setUp(self):
        import server
        self.tmp = tempfile.TemporaryDirectory()
        self.original_state_file = settings.ALARM_STATE_FILE
        settings.ALARM_STATE_FILE = Path(self.tmp.name) / 'alarm_state.json'
        self.client = server.app.test_client()

    def tearDown(self):
        settings.ALARM_STATE_FILE = self.original_state_file
        self.tmp.cleanup()

    def push(self, action, event, next_alarm=None, retry_timestamp=None):
        schedule = {'hasAlarm': next_alarm is not None, 'nextAlarm': next_alarm}
        schedule['scheduledAt' if next_alarm else 'clearedAt'] = event
        return self.client.post('/api/schedule/update', json={
            'timestamp': retry_timestamp or event, 'action': action, 'schedule': schedule})

    def stored(self):
        return statefiles.read_json(settings.ALARM_STATE_FILE)

    def test_set_then_clear(self):
        self.push('schedule_set', '2026-10-19T06:00:00.000Z', '2026-10-19T14:08:00.000Z')
        self.push('schedule_cleared', '2026-10-19T06:00:05.000Z')
        self.assertFalse(self.stored()['hasAlarm'])

    def test_late_retried_clear_does_not_wipe_new_alarm(self):
        # Monty sent clear (06:00:00) then set (06:00:01); the clear's retry
        # arrives last with a fresh top-level timestamp
        self.push('schedule_set', '2026-10-19T06:00:01.000Z', '2026-10-19T14:08:00.000Z')
        response = self.push('schedule_cleared', '2026-10-19T06:00:00.000Z',
                             retry_timestamp='2026-10-19T06:00:07.000Z')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['ignored'])
        self.assertEqual(self.stored()['nextAlarm'], '2026-10-19T14:08:00.000Z')

    def test_health_reports_audio(self):
        audio = self.client.get('/api/health').get_json()['audio']
        self.assertEqual(audio['card'], settings.AUDIO_CARD)
        self.assertIn('present', audio)


if __name__ == '__main__':
    unittest.main()
