#!/usr/bin/env python3
"""
Tests for the alarm's decision logic and the push receiver.
Run on the Pi with the venv (it has Flask):
    venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'core'))
sys.path.insert(0, str(ROOT))

import monty_songs
import settings
import statefiles
from alarm_trigger import alarm_action, PIANOBAR_SONG, song_log_entry, log_song


class AlarmActionTests(unittest.TestCase):
    alarm_at = datetime(2026, 10, 20, 8, 8)
    key = '2026-10-20T14:08:00.000Z'

    def action(self, now, handled=None):
        return alarm_action(now, self.alarm_at, self.key, handled)

    lead = timedelta(seconds=settings.SPEAKER_LEAD_SECONDS)

    def test_waits_before_speaker_lead(self):
        self.assertEqual(self.action(self.alarm_at - self.lead - timedelta(seconds=1)), 'wait')

    def test_starts_early_to_wake_speakers(self):
        # The speakers take ~7 s to wake, so the music can start with the shades
        self.assertEqual(self.action(self.alarm_at - self.lead), 'ring')

    def test_no_lead_waits_for_alarm_time(self):
        self.assertEqual(alarm_action(self.alarm_at - timedelta(seconds=1), self.alarm_at, self.key, None,
                                      lead=timedelta(0)), 'wait')

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


class SongLogTests(unittest.TestCase):
    def test_song_and_station_are_logged(self):
        self.assertEqual(song_log_entry('|>  "Rolling in the Deep" by "Adele" on "21"'),
                         '"Rolling in the Deep" by "Adele" on "21"')
        self.assertEqual(song_log_entry('|>  Station "Morning Hits Radio" (104370043902517433)'),
                         'Station "Morning Hits Radio" (104370043902517433)')

    def test_thumbs_are_logged(self):
        self.assertEqual(song_log_entry('(i) Banning song... Ok.'), '  thumbs down')
        self.assertEqual(song_log_entry('(i) Loving song... Ok.'), '  thumbs up')

    def test_chatter_is_not(self):
        for line in ('(i) Login... Ok.', '(i) Receiving new playlist... Ok.',
                     'Welcome to pianobar (2022.04.01)! Press ? for a list of commands.'):
            self.assertIsNone(song_log_entry(line))

    def test_lines_are_appended_with_the_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'songs.log'
            log_song('--- Alarm for 09:45 ---', when=datetime(2026, 10, 22, 9, 45), path=path)
            log_song('"Save Your Tears" by "The Weeknd" on "Après"', when=datetime(2026, 10, 22, 9, 50), path=path)
            self.assertEqual(path.read_text(encoding='utf-8'),
                             '2026-10-22 09:45  --- Alarm for 09:45 ---\n'
                             '2026-10-22 09:50  "Save Your Tears" by "The Weeknd" on "Après"\n')

    def test_unwritable_log_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_song('x', path=Path(tmp) / 'missing-dir' / 'songs.log')


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


class WakeupSettingsTests(unittest.TestCase):
    def test_valid_settings_are_kept(self):
        from statefiles import clean_wakeup_settings
        clean, warnings = clean_wakeup_settings({'wakeMode': 'mp3', 'mp3Track': 'Beethoven.mp3', 'snoozeMinutes': 12})
        self.assertEqual(clean, {'wakeMode': 'mp3', 'mp3Track': 'Beethoven.mp3', 'snoozeMinutes': 12})
        self.assertEqual(warnings, [])

    def test_missing_and_null_are_silent_defaults(self):
        from statefiles import clean_wakeup_settings
        clean, warnings = clean_wakeup_settings({'mp3Track': None})
        self.assertEqual(clean, {'wakeMode': None, 'mp3Track': None, 'snoozeMinutes': None})
        self.assertEqual(warnings, [])

    def test_bad_values_are_dropped_with_a_warning(self):
        from statefiles import clean_wakeup_settings
        for bad in ({'snoozeMinutes': 0}, {'snoozeMinutes': 31}, {'snoozeMinutes': '12'},
                    {'snoozeMinutes': 12.5}, {'snoozeMinutes': True}, {'wakeMode': 'radio'},
                    {'mp3Track': '../secret.mp3'}, {'mp3Track': 'song.wav'}, {'mp3Track': 7},
                    {'mp3Track': 'a\\b.mp3'}, {'mp3Track': '.hidden.mp3'}, {'mp3Track': 'x\0.mp3'}):
            clean, warnings = clean_wakeup_settings(bad)
            self.assertEqual(set(clean.values()), {None}, bad)
            self.assertEqual(len(warnings), 1, bad)

    def test_real_library_names_are_kept(self):
        from statefiles import clean_wakeup_settings
        for name in ("Kenny Loggins - I'm Alright.mp3", 'Oliver Tree & Robin Schulz - Miss You.mp3',
                     'St-Amour - night lights 🎷.mp3', 'Running Away is Easy - 𝙏𝙞𝙢𝙚 𝙈𝙤𝙫𝙚𝙨 𝙎𝙡𝙤𝙬.mp3',
                     'Tiësto - Rule The World (Tears For Fears, NIIKO X SWAE, GUDFELLA).mp3', 'ART! - Jazzy Liquid DnB.mp3'):
            clean, warnings = clean_wakeup_settings({'mp3Track': name})
            self.assertEqual((clean['mp3Track'], warnings), (name, []))

    def test_monty_wins_then_the_pi_then_settings(self):
        from statefiles import resolve_wakeup
        local = {'mode': 'mp3', 'mp3_track': 'THE_HIT.mp3'}
        wake = resolve_wakeup({'wakeMode': 'pianobar', 'mp3Track': None, 'snoozeMinutes': None}, local)
        self.assertEqual((wake['mode'], wake['mp3_track'], wake['snooze_minutes']),
                         ('pianobar', 'THE_HIT.mp3', settings.SNOOZE_MINUTES))
        self.assertEqual(wake['from'], {'mode': 'set in Monty', 'mp3_track': 'Pi default',
                                        'snooze_minutes': 'Pi default'})


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

    def test_wakeup_settings_stored_and_cleared(self):
        self.client.post('/api/schedule/update', json={
            'timestamp': '2026-10-21T06:00:00.000Z', 'action': 'schedule_set',
            'schedule': {'hasAlarm': True, 'nextAlarm': '2026-10-21T15:00:00.000Z',
                         'scheduledAt': '2026-10-21T06:00:00.000Z',
                         'wakeMode': 'mp3', 'mp3Track': 'Beethoven.mp3', 'snoozeMinutes': 3}})
        self.assertEqual((self.stored()['wakeMode'], self.stored()['mp3Track'], self.stored()['snoozeMinutes']),
                         ('mp3', 'Beethoven.mp3', 3))
        self.push('schedule_cleared', '2026-10-21T06:00:05.000Z')
        self.assertIsNone(self.stored()['snoozeMinutes'])
        self.assertIsNone(self.stored()['wakeMode'])

    def test_bad_setting_still_stores_the_alarm(self):
        self.client.post('/api/schedule/update', json={
            'timestamp': '2026-10-21T06:00:00.000Z', 'action': 'schedule_set',
            'schedule': {'hasAlarm': True, 'nextAlarm': '2026-10-21T15:00:00.000Z',
                         'scheduledAt': '2026-10-21T06:00:00.000Z', 'snoozeMinutes': 99}})
        self.assertTrue(self.stored()['hasAlarm'])
        self.assertIsNone(self.stored()['snoozeMinutes'])

    def test_wakeup_options(self):
        music = Path(self.tmp.name) / 'music'
        (music / 'from-monty').mkdir(parents=True)
        for name in ('B.mp3', 'A.mp3', 'notes.txt', 'from-monty/c from Monty.mp3', 'from-monty/d.mp3.part'):
            (music / name).touch()
        originals = settings.MUSIC_DIR, settings.MONTY_SONGS_DIR
        settings.MUSIC_DIR, settings.MONTY_SONGS_DIR = music, music / 'from-monty'
        try:
            options = self.client.get('/api/wakeup/options').get_json()
        finally:
            settings.MUSIC_DIR, settings.MONTY_SONGS_DIR = originals
        # Songs from Monty by bare name, as Monty names them; never a partial download
        self.assertEqual(options['mp3Tracks'], ['A.mp3', 'B.mp3', 'c from Monty.mp3'])
        self.assertTrue(options['fetchesFromMonty'])
        self.assertTrue(options['modes']['mp3']['available'])
        self.assertEqual(options['modes']['fm']['available'], settings.FM_AVAILABLE)
        self.assertIn('reason', options['modes']['fm'])
        self.assertEqual(options['snoozeMinutes'], dict(zip(('min', 'max'), settings.SNOOZE_MINUTES_RANGE)))

    def test_health_reports_audio(self):
        audio = self.client.get('/api/health').get_json()['audio']
        self.assertEqual(audio['card'], settings.AUDIO_CARD)
        self.assertIn('present', audio)


class MontySongsTests(unittest.TestCase):
    """Downloads from a stand-in for Monty's GET /api/jukebox/library/{name}/file"""
    KENNY = "Kenny Loggins - I'm Alright.mp3"
    SAX = 'St-Amour - night lights 🎷.mp3'

    @classmethod
    def setUpClass(cls):
        library = {cls.KENNY: b'ID3 kenny ' * 1000, cls.SAX: b'ID3 sax ' * 1000}
        cls.library, cls.requests = library, []
        requests = cls.requests

        class Monty(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                name = urllib.parse.unquote(self.path[len('/api/jukebox/library/'):-len('/file')])
                if name == 'cut-off.mp3':  # Promises 100 kB, sends 10 bytes and hangs up
                    self.send_response(200)
                    self.send_header('Content-Length', '100000')
                    self.end_headers()
                    self.wfile.write(b'x' * 10)
                    return
                if name not in library:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'audio/mpeg')
                self.send_header('Content-Length', str(len(library[name])))
                self.end_headers()
                self.wfile.write(library[name])

            def log_message(self, *args):
                pass

        cls.monty = ThreadingHTTPServer(('127.0.0.1', 0), Monty)
        threading.Thread(target=cls.monty.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.monty.shutdown()
        cls.monty.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        music = Path(self.tmp.name) / 'music'
        music.mkdir()
        (music / settings.DEFAULT_MP3).write_bytes(b'ID3 default')
        self.originals = (settings.MUSIC_DIR, settings.MONTY_SONGS_DIR, settings.MONTY_URL,
                          settings.MONTY_SONGS_MAX_MB, settings.ALARM_STATE_FILE)
        settings.MUSIC_DIR, settings.MONTY_SONGS_DIR = music, music / 'from-monty'
        settings.MONTY_URL = f'http://127.0.0.1:{self.monty.server_port}'
        settings.ALARM_STATE_FILE = Path(self.tmp.name) / 'alarm_state.json'
        self.requests.clear()

    def tearDown(self):
        (settings.MUSIC_DIR, settings.MONTY_SONGS_DIR, settings.MONTY_URL,
         settings.MONTY_SONGS_MAX_MB, settings.ALARM_STATE_FILE) = self.originals
        self.tmp.cleanup()

    def test_names_are_encoded_and_saved_as_monty_names_them(self):
        for name in (self.KENNY, self.SAX):
            ok, message = monty_songs.download(name)
            self.assertTrue(ok, message)
            self.assertEqual(monty_songs.track_path(name).read_bytes(), self.library[name])
        self.assertEqual(self.requests[0], '/api/jukebox/library/Kenny%20Loggins%20-%20I%27m%20Alright.mp3/file')
        self.assertEqual(monty_songs.mp3_to_play(self.KENNY), (settings.MONTY_SONGS_DIR / self.KENNY, None))

    def test_path_escapes_are_refused_without_asking_monty(self):
        for bad in ('../alarm_state.json', '../../x.mp3', 'a/b.mp3', 'a\\b.mp3', '.hidden.mp3', 'x\0.mp3', 'song.wav'):
            self.assertFalse(monty_songs.download(bad)[0], bad)
            self.assertIsNone(monty_songs.track_path(bad), bad)
        self.assertEqual(self.requests, [])

    def test_failed_download_plays_the_default(self):
        ok, why = monty_songs.download('Not In The Library.mp3')
        self.assertFalse(ok)
        self.assertIn('404', why)
        path, problem = monty_songs.mp3_to_play('Not In The Library.mp3')
        self.assertEqual(path, settings.MUSIC_DIR / settings.DEFAULT_MP3)
        self.assertIn("isn't on the Pi", problem)

    def test_partial_download_is_never_played(self):
        ok, why = monty_songs.download('cut-off.mp3')
        self.assertFalse(ok)
        self.assertIn('10 of 100000', why)
        self.assertIsNone(monty_songs.track_path('cut-off.mp3'))
        self.assertEqual(list(settings.MONTY_SONGS_DIR.iterdir()), [])  # No .part left behind

    def test_cleanup_keeps_the_alarms_song_and_the_newest(self):
        folder = settings.MONTY_SONGS_DIR
        folder.mkdir()
        now = time.time()
        for age, name in enumerate(('newest.mp3', 'newer.mp3', 'older.mp3', 'alarm song.mp3')):
            (folder / name).write_bytes(b'x' * monty_songs.MB)
            os.utime(folder / name, (now - age * 60, now - age * 60))
        (folder / 'stale.mp3.part').touch()
        os.utime(folder / 'stale.mp3.part', (now - 7200, now - 7200))
        (folder / 'live.mp3.part').touch()  # A download in progress
        settings.MONTY_SONGS_MAX_MB = 2

        deleted = monty_songs.clean_up(keep={'alarm song.mp3'})
        self.assertEqual(deleted, ['newer.mp3', 'older.mp3'])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['alarm song.mp3', 'live.mp3.part', 'newest.mp3'])

    def test_push_downloads_a_missing_song_once(self):
        import server
        client = server.app.test_client()
        push = {'timestamp': '2026-10-22T06:00:00.000Z', 'action': 'schedule_set',
                'schedule': {'hasAlarm': True, 'nextAlarm': '2026-10-23T14:00:00.000Z',
                             'scheduledAt': '2026-10-22T06:00:00.000Z', 'wakeMode': 'mp3', 'mp3Track': self.KENNY}}
        self.assertTrue(client.post('/api/schedule/update', json=push).get_json()['success'])
        for thread in threading.enumerate():
            if thread.name == 'monty-song':
                thread.join(5)
        self.assertIsNotNone(monty_songs.track_path(self.KENNY))
        # The hourly sync re-pushes the same song: already here, so no second download
        client.post('/api/schedule/update', json=push)
        self.assertEqual(len(self.requests), 1)
        self.assertIsNone(server.want_song(None))


if __name__ == '__main__':
    unittest.main()
