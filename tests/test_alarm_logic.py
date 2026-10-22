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


class ButtonLightTests(unittest.TestCase):
    def test_display_text_maps_to_state(self):
        from button_leds import alarm_state
        self.assertEqual(alarm_state('WAKE!'), 'ringing')
        self.assertEqual(alarm_state('SNZ 07:18'), 'snoozing')
        self.assertEqual(alarm_state(''), 'idle')

    def test_every_state_has_a_valid_look_for_both_buttons(self):
        from button_leds import MODES
        self.assertEqual(set(settings.BUTTON_LIGHTS), {'idle', 'ringing', 'snoozing', 'stopped'})
        for state, looks in settings.BUTTON_LIGHTS.items():
            self.assertEqual(set(looks), {'snooze', 'check'}, state)
            for (rgb, effect) in looks.values():
                self.assertIn(effect, MODES, state)
                self.assertTrue(all(0 <= c <= 255 for c in rgb), state)

    def test_flash_is_a_valid_look(self):
        from button_leds import MODES
        rgb, effect = settings.BUTTON_FLASH_LIGHT
        self.assertIn(effect, MODES)
        self.assertTrue(all(0 <= c <= 255 for c in rgb))

    def test_idle_is_dark(self):
        for rgb, _ in settings.BUTTON_LIGHTS['idle'].values():
            self.assertEqual(rgb, (0, 0, 0))


class PianobarFifoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctl = Path(self.tmp.name) / 'pianobar' / 'ctl'

    def tearDown(self):
        self.tmp.cleanup()

    def test_send_without_pianobar_is_false_not_a_hang(self):
        import pianobar
        pianobar.ensure_fifo(self.ctl)
        self.assertFalse(pianobar.send('-', self.ctl))

    def test_send_reaches_a_listening_pianobar(self):
        import os
        import pianobar
        pianobar.ensure_fifo(self.ctl)
        reader = os.open(self.ctl, os.O_RDONLY | os.O_NONBLOCK)  # Stands in for pianobar
        try:
            self.assertTrue(pianobar.send('-', self.ctl))
            self.assertEqual(os.read(reader, 16), b'-')
        finally:
            os.close(reader)

    def test_plain_file_is_replaced_by_a_fifo(self):
        import stat
        import pianobar
        self.ctl.parent.mkdir(parents=True)
        self.ctl.write_text('n\n')  # What "echo n > ctl" leaves when no FIFO exists
        pianobar.ensure_fifo(self.ctl)
        self.assertTrue(stat.S_ISFIFO(self.ctl.stat().st_mode))

    def test_missing_fifo_is_false(self):
        import pianobar
        self.assertFalse(pianobar.send('-', self.ctl))


class SpeakerRelayTests(unittest.TestCase):
    """pinctrl's lines as seen on the Pi on 2026-10-21"""

    def test_driven_low_is_on(self):
        from speakers import relay_on_from_pinctrl
        self.assertTrue(relay_on_from_pinctrl(' 4: op -- pu | lo // GPIO4 = output'))

    def test_released_input_is_off(self):
        from speakers import relay_on_from_pinctrl
        self.assertFalse(relay_on_from_pinctrl(' 4: ip    pu | hi // GPIO4 = input'))

    def test_driven_high_is_off(self):
        from speakers import relay_on_from_pinctrl
        self.assertFalse(relay_on_from_pinctrl(' 4: op dh pu | hi // GPIO4 = output'))

    def test_garbage_is_off(self):
        from speakers import relay_on_from_pinctrl
        self.assertFalse(relay_on_from_pinctrl(''))

    def test_settle_covers_the_amp(self):
        # The ZA3 unmutes ~6 s after the click and the ZD3 appears at ~4 s;
        # pianobar takes ~1 s more, so less than 2 s of settle clips intros
        self.assertGreaterEqual(settings.SPEAKER_SETTLE_SECONDS, 2)
        self.assertGreater(settings.SPEAKER_WAIT_SECONDS, 5)


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
