#!/usr/bin/env python3
"""
Alarm Trigger for Monty Alarm Clock
Watches the schedule Monty pushes (alarm_state.json, written by server.py),
rings at the alarm time, and handles snooze and stop from the buttons.

Each alarm is remembered by its nextAlarm value once it has rung (or been
missed), so it never rings twice and any number of alarms a day work.

At alarm time it clicks the speaker relay on (core/speakers.py), waits for
the ZD3 to wake and the ZA3 to unmute, then starts the music. The speakers
stay on through snoozes and go off SPEAKER_OFF_DELAY_SECONDS after the alarm.

Every song it plays, with the station, thumbs and snoozes, is added to
songs.log (settings.SONG_LOG_FILE), which outlasts the journal.

Run with --test-music [seconds] to play the wake-up music through the
alarm's audio path without waiting for an alarm.
"""

import asyncio
import re
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import monty_songs
import pianobar
import settings
import speakers
from statefiles import (read_json, write_json, pushed_alarm, load_wakeup_config,
                        pushed_wakeup_settings, resolve_wakeup, describe_wakeup,
                        describe_alarm, take_signal, write_display)

ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
# pianobar's song line: |>  "Cheap Thrills" by "Sia" on "..." (its station line also starts with |>)
PIANOBAR_SONG = re.compile(r'^\|>\s+".*" by "')
# pianobar's replies when a thumbs down (the Check button) or thumbs up goes through
PIANOBAR_RATINGS = {'(i) Banning song... Ok.': 'thumbs down', '(i) Loving song... Ok.': 'thumbs up'}
NOT_LOGGED = object()


def alarm_action(now, alarm_at, alarm_key, handled_alarm,
                 late_grace=timedelta(minutes=settings.LATE_GRACE_MINUTES)):
    """What to do about the pushed alarm right now: 'ring', 'missed' or 'wait'"""
    if alarm_at is None or alarm_key == handled_alarm or now < alarm_at:
        return 'wait'
    if now - alarm_at <= late_grace:
        return 'ring'
    return 'missed'


def song_log_entry(line):
    """What a pianobar output line adds to the song log, or None"""
    if line.startswith('|>'):
        return line[2:].strip()  # Station "..." or "Title" by "Artist" on "Album"
    if line in PIANOBAR_RATINGS:
        return f"  {PIANOBAR_RATINGS[line]}"
    return None


def log_song(entry, when=None, path=None):
    """Add a dated line to the song log. Opened per line so deleting the file
    is safe, and never raises: a full SD card mustn't stop the alarm."""
    when = when or datetime.now()
    try:
        with open(path or settings.SONG_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{when:%Y-%m-%d %H:%M}  {entry}\n")
    except OSError as e:
        print(f"   ⚠️ Couldn't write the song log: {e}")


def set_volume(percent):
    """Set the alarm's softvol control. Returns (ok, error text)."""
    result = subprocess.run(
        ['amixer', '-q', '-M', '-c', settings.AUDIO_CARD, 'sset', settings.VOLUME_CONTROL, f'{percent}%'],
        capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def audio_device_present():
    return Path(f'/proc/asound/{settings.AUDIO_CARD}').exists()


def running(name):
    return subprocess.run(['pgrep', '-x', name], capture_output=True).returncode == 0


async def stop_all_players(names=('pianobar', 'mpg123'), timeout=2.0):
    """The sound card takes one player at a time, and two pianobars would split
    the control FIFO's commands. Ask every pianobar and mpg123 on the Pi to quit
    (the alarm's or one started by hand), then force any that don't. -x matches
    the program name exactly, so core/pianobar.py and editors are left alone."""
    for name in names:
        subprocess.run(['pkill', '-x', name], capture_output=True)
    deadline = time.monotonic() + timeout
    while any(running(name) for name in names):
        if time.monotonic() >= deadline:
            for name in names:
                if running(name):
                    print(f"   ⚠️ {name} didn't quit - killing it")
                    subprocess.run(['pkill', '-KILL', '-x', name], capture_output=True)
            return
        await asyncio.sleep(0.1)


class AlarmTrigger:
    def __init__(self):
        self.player = None          # The running pianobar or mpg123
        self.player_name = None
        self.player_started = None
        self.output_task = None     # Drains the player's output into the journal
        self.volume_task = None
        self.speakers_off_at = None  # When to switch the speakers off after an alarm
        self.wake = None             # The ringing alarm's settings (resolve_wakeup), fixed when it starts
        state = read_json(settings.TRIGGER_STATE_FILE, {}) or {}
        self.handled_alarm = state.get('handled_alarm')
        self.logged_alarm = NOT_LOGGED
        settings.SIGNALS_DIR.mkdir(parents=True, exist_ok=True)

    def mark_handled(self, alarm_key, result):
        """Remember this alarm so it never rings twice"""
        self.handled_alarm = alarm_key
        write_json(settings.TRIGGER_STATE_FILE, {
            'handled_alarm': alarm_key,
            'result': result,
            'at': datetime.now().isoformat()
        })

    def log_schedule(self, alarm_key, alarm_at):
        """Log the next alarm when it changes, not every check"""
        if alarm_key == self.logged_alarm:
            return
        self.logged_alarm = alarm_key
        if alarm_at is None:
            print("💤 No alarm set")
        elif alarm_key == self.handled_alarm:
            print(f"✔️ Alarm for {alarm_at:%a %H:%M} already handled")
        else:
            print(f"⏰ Next alarm: {describe_alarm(alarm_at)}")

    def discard_stray_presses(self):
        """Presses while nothing is ringing must not carry over to the next alarm"""
        if take_signal(settings.SNOOZE_SIGNAL):
            print("💤 Snooze pressed with no alarm ringing - ignored")
        if take_signal(settings.STOP_SIGNAL):
            print("🛑 Stop pressed with no alarm ringing - ignored")

    # ---------- Speakers ----------

    async def wake_speakers(self):
        """Click the speaker relay on and wait until the ZD3 can play and the ZA3
        has unmuted. A ZD3 that's already on needs no wait. Never raises: if the
        ZD3 doesn't wake, the alarm goes ahead anyway."""
        self.speakers_off_at = None
        if audio_device_present():
            speakers.switch(True)
            return
        print("🔈 Speakers on, waiting for the ZD3 to wake...")
        clicked = time.monotonic()
        deadline = clicked + settings.SPEAKER_WAIT_SECONDS
        speakers.switch(True)
        while not audio_device_present():
            if time.monotonic() >= deadline:
                print(f"🔇 WARNING: the ZD3 didn't wake within {settings.SPEAKER_WAIT_SECONDS}s "
                      "- the alarm may be silent!")
                return
            await asyncio.sleep(0.1)
        appeared = time.monotonic()
        # The ZD3 is listed a moment before it can play, and its first stream after
        # waking snaps as it switches clock. Play silence until it works, while the
        # ZA3 is still muted, so the music starts clean.
        while not await self.play_silence():
            if time.monotonic() >= deadline:
                print("⚠️ The ZD3 is on USB but won't play yet - starting the music anyway")
                return
            await asyncio.sleep(0.3)
        await asyncio.sleep(max(0.0, settings.SPEAKER_SETTLE_SECONDS - (time.monotonic() - appeared)))
        print(f"🔊 Speakers ready {time.monotonic() - clicked:.1f}s after the click")

    async def play_silence(self):
        """A second of 44.1 kHz silence through the alarm's audio path. True if it played."""
        aplay = await asyncio.create_subprocess_exec(
            'aplay', '-q', '-d', '1', '-f', 'cd', '/dev/zero',
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            return await asyncio.wait_for(aplay.wait(), timeout=5) == 0
        except asyncio.TimeoutError:
            aplay.kill()
            await aplay.wait()
            return False

    def speakers_off_when_due(self):
        """Switch the speakers off SPEAKER_OFF_DELAY_SECONDS after an alarm. Anything
        the Pi plays meanwhile (pianobar from SSH, say) restarts the countdown."""
        if self.speakers_off_at is None:
            return
        if speakers.zd3_playing():
            self.speakers_off_at = datetime.now() + timedelta(seconds=settings.SPEAKER_OFF_DELAY_SECONDS)
        elif datetime.now() >= self.speakers_off_at:
            if speakers.switch(False):
                print("🔈 Speakers off")
            self.speakers_off_at = None

    # ---------- Music ----------

    async def watch_output(self, stream, label, song_started=None):
        """Log the player's useful output lines, copy pianobar's songs to the
        song log and spot Pandora's first song.
        Reads in chunks because pianobar redraws its clock with \\r, not \\n."""
        buffer = ''
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            buffer += ANSI_ESCAPE.sub('', chunk.decode(errors='replace'))
            *lines, buffer = re.split(r'[\r\n]', buffer)
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):  # '#  -03:21/03:45' is the clock
                    continue
                print(f"   [{label}] {line}")
                entry = song_log_entry(line) if label == 'pianobar' else None
                if entry is not None:
                    log_song(entry)
                if song_started is not None and PIANOBAR_SONG.match(line):
                    song_started.set()

    async def start_player(self, name, *args, song_started=None):
        self.player = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,   # pianobar takes commands on stdin; keep it open
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        self.player_name = name
        self.player_started = datetime.now()
        self.output_task = asyncio.create_task(self.watch_output(self.player.stdout, name, song_started))

    async def start_pandora(self):
        """Start pianobar and wait for its first song. False if none starts in time."""
        print("   Starting Pandora (pianobar)...")
        try:
            pianobar.ensure_fifo()  # So the Check button's thumbs down reaches it
        except OSError as e:
            print(f"   ⚠️ No pianobar control FIFO ({e}) - thumbs down won't work")
        song_started = asyncio.Event()
        await self.start_player('pianobar', 'pianobar', song_started=song_started)
        # Stop waiting early if pianobar quits (no network, bad login)
        waits = {asyncio.create_task(song_started.wait()), asyncio.create_task(self.player.wait())}
        _, pending = await asyncio.wait(waits, timeout=settings.PANDORA_START_SECONDS,
                                        return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        return song_started.is_set()

    async def start_mp3(self, track):
        # Only what's already on the SD card: a song from Monty is downloaded when it's pushed
        path, problem = monty_songs.mp3_to_play(track)
        if problem:
            print(f"   ❌ {problem} (a song from Monty that hasn't downloaded?) - playing {path.name}")
        print(f"   Playing MP3: {path.name}")
        log_song(f"MP3 {path.name}" + (f" ({problem})" if problem else ""))
        await self.start_player('mpg123', 'mpg123', '-q', '-o', 'alsa', '--loop', '-1', str(path))

    async def prepare_volume(self):
        """Start quiet. softvol only creates its control the first time the
        device is opened, so play a second of silence if it isn't there yet."""
        if not audio_device_present():
            print(f"🔇 WARNING: {settings.AUDIO_CARD} is not connected - the alarm will be silent!")
        ok, err = set_volume(settings.MIN_VOLUME)
        if not ok:
            subprocess.run(['aplay', '-q', '-d', '1', '-f', 'cd', '/dev/zero'],
                           capture_output=True, timeout=10)
            ok, err = set_volume(settings.MIN_VOLUME)
        if not ok:
            print(f"⚠️ Could not set the alarm volume: {err}")

    async def ramp_volume(self):
        """Raise the volume from MIN_VOLUME to MAX_VOLUME over VOLUME_RAMP_SECONDS"""
        steps = max(1, (settings.MAX_VOLUME - settings.MIN_VOLUME) // 2)
        for step in range(1, steps + 1):
            await asyncio.sleep(settings.VOLUME_RAMP_SECONDS / steps)
            ok, _ = set_volume(settings.MIN_VOLUME + (settings.MAX_VOLUME - settings.MIN_VOLUME) * step // steps)
        if ok:
            print(f"🔊 Volume at {settings.MAX_VOLUME}%")

    async def start_music(self):
        """Start the wake-up music for the configured mode, falling back to the MP3"""
        print("🎵 Starting wake-up music...")
        # The alarm wins over anything playing
        await stop_all_players()
        await self.prepare_volume()

        wake = self.wake_settings()
        mode = wake['mode']
        print(f"   Wake-up mode: {mode.upper()}")
        if mode == 'fm' and not settings.FM_AVAILABLE:
            print("   📻 FM radio isn't built yet - using Pandora")
            mode = 'pianobar'
        elif mode not in settings.WAKE_MODES:
            print(f"   ⚠️ Unknown wake-up mode {mode!r} - using Pandora")
            mode = 'pianobar'

        if mode == 'pianobar':
            if not await self.start_pandora():
                print(f"   ⚠️ No Pandora song after {settings.PANDORA_START_SECONDS}s - falling back to MP3")
                await self.stop_player()
                await self.start_mp3(wake['mp3_track'])
        else:
            await self.start_mp3(wake['mp3_track'])

        self.volume_task = asyncio.create_task(self.ramp_volume())

    async def restart_if_died(self):
        """If the player quits mid-alarm (lost network, bad file), switch to the MP3"""
        if self.player is None or self.player.returncode is None:
            return
        if datetime.now() - self.player_started < timedelta(seconds=30):
            return  # Don't spin (or flood the journal) if the MP3 can't play either
        print(f"⚠️ {self.player_name} stopped (exit {self.player.returncode}) - switching to MP3")
        await self.stop_player()
        await self.start_mp3(self.wake_settings()['mp3_track'])

    def wake_settings(self):
        """The ringing alarm's settings, or (for --test-music) what the next alarm would use"""
        return self.wake or resolve_wakeup(pushed_wakeup_settings(), load_wakeup_config())

    async def stop_player(self):
        if self.player is not None and self.player.returncode is None:
            self.player.terminate()
            try:
                await asyncio.wait_for(self.player.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.player.kill()
                await self.player.wait()
        if self.output_task is not None:
            self.output_task.cancel()
        self.player = None
        self.output_task = None

    async def stop_music(self):
        if self.volume_task is not None and not self.volume_task.done():
            self.volume_task.cancel()
        self.volume_task = None
        await self.stop_player()

    # ---------- Alarm ----------

    async def wait_for_press(self, deadline):
        """Ring until Stop, Snooze or the deadline: returns 'stop', 'snooze' or 'timeout'"""
        while True:
            if take_signal(settings.STOP_SIGNAL):
                return 'stop'
            if take_signal(settings.SNOOZE_SIGNAL):
                return 'snooze'
            if datetime.now() >= deadline:
                return 'timeout'
            await self.restart_if_died()
            await asyncio.sleep(0.2)

    def press_before_music(self):
        """Stop or Snooze pressed while the speakers were waking: 'stop', 'snooze' or None"""
        if take_signal(settings.STOP_SIGNAL):
            return 'stop'
        if take_signal(settings.SNOOZE_SIGNAL):
            return 'snooze'
        return None

    async def wait_out_snooze(self, until):
        """Wait out a snooze. True if Stop was pressed meanwhile."""
        while datetime.now() < until:
            if take_signal(settings.STOP_SIGNAL):
                return True
            if take_signal(settings.SNOOZE_SIGNAL):
                print("💤 Already snoozing")
            await asyncio.sleep(0.2)
        return False

    async def ring(self, alarm_key, alarm_at):
        """Ring until stopped, with any number of snoozes, for up to ALARM_DURATION_MINUTES"""
        print(f"\n⏰ ALARM! Set for {alarm_at:%H:%M}, ringing at {datetime.now():%H:%M:%S}")
        self.mark_handled(alarm_key, 'rang')
        # Read once: Monty clears its one-shot wake-up after firing, and that
        # mustn't change the alarm that's ringing
        self.wake = resolve_wakeup(pushed_wakeup_settings(), load_wakeup_config())
        print(f"🎛️ Wake-up: {describe_wakeup(self.wake)}")
        log_song(f"--- Alarm for {alarm_at:%H:%M} ---")
        # Only presses made while it rings count
        take_signal(settings.SNOOZE_SIGNAL)
        take_signal(settings.STOP_SIGNAL)
        deadline = datetime.now() + timedelta(minutes=settings.ALARM_DURATION_MINUTES)

        try:
            write_display("WAKE!")  # The button lights come on with the click
            await self.wake_speakers()
            while True:
                write_display("WAKE!")
                outcome = self.press_before_music()
                if outcome is None:
                    await self.start_music()
                    outcome = await self.wait_for_press(deadline)
                    await self.stop_music()
                if outcome == 'stop':
                    print("✋ Alarm stopped")
                    break
                if outcome == 'timeout':
                    print(f"⏱️ Alarm stopped itself after {settings.ALARM_DURATION_MINUTES} minutes")
                    break

                snooze_until = min(datetime.now() + timedelta(minutes=self.wake['snooze_minutes']), deadline)
                print(f"😴 Snoozing until {snooze_until:%H:%M}")
                log_song(f"  snoozed until {snooze_until:%H:%M}")
                write_display(f"SNZ {snooze_until:%H:%M}")
                if await self.wait_out_snooze(snooze_until):
                    print("✋ Alarm stopped during snooze")
                    break
                if datetime.now() >= deadline:
                    print(f"⏱️ Alarm stopped itself after {settings.ALARM_DURATION_MINUTES} minutes")
                    break
                print("⏰ Snooze over - back to the music")
        finally:
            await self.stop_music()
            write_display("")
            self.wake = None
            # Speakers stay on a while, in case of music while getting ready
            self.speakers_off_at = datetime.now() + timedelta(seconds=settings.SPEAKER_OFF_DELAY_SECONDS)
        print(f"✅ Alarm finished - speakers off at {self.speakers_off_at:%H:%M:%S} unless something plays")

    def check_clock(self):
        """There's no hardware clock: until NTP syncs, the time may be days off"""
        result = subprocess.run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                                capture_output=True, text=True)
        if result.stdout.strip() != 'yes':
            print("⚠️ System clock is not NTP-synchronized yet - alarm times may be off")

    async def monitor_loop(self):
        """Main monitoring loop"""
        print("🔍 Starting alarm monitor...")
        print(f"   Snooze: {settings.SNOOZE_MINUTES} min unless Monty sends another, auto-stop: {settings.ALARM_DURATION_MINUTES} min, "
              f"late grace: {settings.LATE_GRACE_MINUTES} min")
        print(f"   Volume ramp: {settings.MIN_VOLUME}% to {settings.MAX_VOLUME}% over {settings.VOLUME_RAMP_SECONDS}s "
              f"on {settings.AUDIO_CARD} ({'awake' if audio_device_present() else 'in standby or unplugged'})")
        relay = speakers.is_on()
        print(f"   Speakers: relay on GPIO {settings.SPEAKER_TRIGGER_GPIO} is "
              f"{ {True: 'on', False: 'off', None: 'UNREADABLE'}[relay] }, "
              f"settle {settings.SPEAKER_SETTLE_SECONDS}s, off {settings.SPEAKER_OFF_DELAY_SECONDS}s after an alarm")
        self.check_clock()
        # A ring never survives a restart, so a WAKE! or SNZ left by a power cut
        # is stale; clear it so the button lights don't show it all night
        write_display("")
        # Speakers left on by a crash mid-alarm go off after the usual delay
        if relay:
            self.speakers_off_at = datetime.now() + timedelta(seconds=settings.SPEAKER_OFF_DELAY_SECONDS)
            print(f"🔈 Speakers were left on - off at {self.speakers_off_at:%H:%M:%S} unless something plays")

        while True:
            try:
                alarm_key, alarm_at = pushed_alarm()
                self.log_schedule(alarm_key, alarm_at)
                action = alarm_action(datetime.now(), alarm_at, alarm_key, self.handled_alarm)
                if action == 'ring':
                    await self.ring(alarm_key, alarm_at)
                    self.logged_alarm = NOT_LOGGED
                elif action == 'missed':
                    print(f"⚠️ Missed the alarm for {describe_alarm(alarm_at)}: "
                          f"more than {settings.LATE_GRACE_MINUTES} minutes late")
                    self.mark_handled(alarm_key, 'missed')
                else:
                    self.discard_stray_presses()
                    self.speakers_off_when_due()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"❌ Monitor error: {e}")
                traceback.print_exc()

            await asyncio.sleep(settings.CHECK_INTERVAL)

    async def test_music(self, seconds):
        """Play the wake-up music through the alarm path, with the speaker wake-up
        and the volume ramp. Speakers that were off go off again afterwards."""
        was_on = speakers.is_on()
        log_song("--- Music test ---")
        try:
            await self.wake_speakers()
            await self.start_music()
            await asyncio.sleep(seconds)
        finally:
            await self.stop_music()
            if was_on is False:
                speakers.switch(False)
        print("✅ Music test done")


async def main():
    print(f"[{datetime.now():%H:%M:%S}] Alarm trigger starting...", flush=True)
    trigger = AlarmTrigger()

    # Turn SIGTERM/SIGINT into a cancel so the music stops on the way out
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)

    try:
        if len(sys.argv) > 1 and sys.argv[1] == '--test-music':
            await trigger.test_music(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        else:
            print("⏰ Monty Alarm Clock Trigger")
            print("=" * 40)
            await trigger.monitor_loop()
    except asyncio.CancelledError:
        print("\n🛑 Shutting down alarm trigger...")
    finally:
        await trigger.stop_music()


if __name__ == "__main__":
    asyncio.run(main())
