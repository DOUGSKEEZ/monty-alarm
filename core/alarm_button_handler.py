#!/usr/bin/env python3
"""
Alarm Clock Button Handler using USB single-key keyboards
Maps KEY_A events to SNOOZE and CHECK ALARM functions:
  Snooze (left):  press to snooze for 9 minutes; hold 1.1 s while pianobar
                  plays to skip to the next song (no thumbs down)
  Check (right):  hold 1.1 s to stop the alarm; tap while pianobar plays
                  (the alarm's or one started by hand) for a Pandora thumbs
                  down, which skips the song; any other tap logs the next alarm
Talks to alarm_trigger.py through signal files in signals/.
Runs as user pi, which can read the buttons through the input group.
"""

import asyncio
import signal
from datetime import datetime

from evdev import InputDevice, ecodes

import pianobar
import settings
from statefiles import pushed_alarm, describe_alarm, send_signal, read_display

KEY_PRESS, KEY_RELEASE = 1, 0  # (2 is key repeat, ignored)


class AlarmButtonHandler:
    def __init__(self):
        self.hold_task = None         # Check
        self.snooze_hold_task = None

    async def watch(self, path, name, on_key):
        """Read one button forever, reopening it if it's unplugged or missing"""
        reported_missing = False
        while True:
            try:
                device = InputDevice(path)
                device.grab()  # Keep the presses from typing "a" on the console
            except OSError as e:
                if not reported_missing:
                    print(f"❌ {name} button not available at {path}: {e} (retrying)")
                    reported_missing = True
                await asyncio.sleep(2)
                continue

            reported_missing = False
            print(f"✅ {name} button connected: {device.name} ({path.rsplit('usb-0:', 1)[-1]})")
            try:
                async for event in device.async_read_loop():
                    if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_A:
                        await on_key(event.value)
            except OSError as e:
                print(f"⚠️ {name} button disconnected: {e}")
            finally:
                try:
                    device.close()
                except OSError:
                    pass
            await asyncio.sleep(1)

    async def on_snooze_key(self, value):
        """Snooze on release, so a hold can mean skip instead"""
        if value == KEY_PRESS:
            if self.snooze_hold_task:
                self.snooze_hold_task.cancel()
            self.snooze_hold_task = asyncio.create_task(self.skip_after_hold())
        elif value == KEY_RELEASE and self.snooze_hold_task:
            if not self.snooze_hold_task.done():
                self.snooze_hold_task.cancel()
                self.snooze()  # Released before the hold time: a press
            self.snooze_hold_task = None

    def snooze(self):
        print(f"\n💤 SNOOZE pressed at {datetime.now():%H:%M:%S}")
        send_signal(settings.SNOOZE_SIGNAL)

    async def skip_after_hold(self):
        """Holding Snooze skips pianobar's song without a thumbs down. With no
        pianobar playing (MP3, or the speakers still waking) a hold just snoozes."""
        await asyncio.sleep(settings.LONG_PRESS_SECONDS)
        if self.send_to_pianobar('n'):
            print(f"\n⏭️ SNOOZE held {settings.LONG_PRESS_SECONDS}s at {datetime.now():%H:%M:%S} - next song")
            send_signal(settings.SNOOZE_FLASH_SIGNAL)
        else:
            self.snooze()

    def send_to_pianobar(self, keys):
        """True if a running pianobar got the keys"""
        try:
            return pianobar.send(keys)
        except OSError as e:
            print(f"⚠️ Couldn't reach pianobar: {e}")
            return False

    async def on_check_key(self, value):
        if value == KEY_PRESS:
            if self.hold_task:
                self.hold_task.cancel()
            self.hold_task = asyncio.create_task(self.stop_after_hold())
        elif value == KEY_RELEASE and self.hold_task:
            if not self.hold_task.done():
                self.hold_task.cancel()
                self.on_check_tap()  # Released before the hold time: a tap
            self.hold_task = None

    def on_check_tap(self):
        """Thumbs down if pianobar is playing, otherwise log the alarm status"""
        if self.send_to_pianobar('-'):
            print(f"\n👎 CHECK tapped at {datetime.now():%H:%M:%S} - thumbs down sent to pianobar")
            send_signal(settings.CHECK_FLASH_SIGNAL)
        else:
            self.log_alarm_status()

    async def stop_after_hold(self):
        """Stop as soon as the hold time is reached, without waiting for release"""
        await asyncio.sleep(settings.LONG_PRESS_SECONDS)
        print(f"\n🛑 CHECK held {settings.LONG_PRESS_SECONDS}s at {datetime.now():%H:%M:%S} - stopping alarm")
        send_signal(settings.STOP_SIGNAL)

    def log_alarm_status(self):
        """Tap on Check: log what the alarm is doing (there's no screen yet)"""
        print(f"\n🔍 CHECK tapped at {datetime.now():%H:%M:%S}")
        display = read_display()
        if display == "WAKE!":
            print("   🔔 Alarm is ringing - hold Check to stop it")
        elif display.startswith("SNZ"):
            print(f"   😴 Snoozing until {display[4:]}")
        _, alarm_at = pushed_alarm()
        if alarm_at is None:
            print("   💤 No alarm set")
        elif alarm_at < datetime.now():
            print(f"   💤 No upcoming alarm (last one: {alarm_at:%a %H:%M})")
        else:
            print(f"   ⏰ Next alarm: {describe_alarm(alarm_at)}")


async def main():
    handler = AlarmButtonHandler()

    print("\n🎯 Alarm Clock Button Handler Started")
    print("=" * 50)
    print(f"SNOOZE button (USB port {settings.SNOOZE_PORT}):")
    print(f"  • Press to snooze (length set in Monty, {settings.SNOOZE_MINUTES} min by default)")
    print(f"  • Hold {settings.LONG_PRESS_SECONDS} seconds while pianobar plays: next song")
    print(f"\nCHECK button (USB port {settings.CHECK_PORT}):")
    print(f"  • Hold {settings.LONG_PRESS_SECONDS} seconds to stop alarm")
    print("  • Tap while pianobar plays: thumbs down on the Pandora song (skips it)")
    print("  • Tap at other times to log the next alarm\n")

    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)

    try:
        await asyncio.gather(
            *(handler.watch(path, "SNOOZE", handler.on_snooze_key) for path in settings.SNOOZE_DEVICES),
            *(handler.watch(path, "CHECK", handler.on_check_key) for path in settings.CHECK_DEVICES),
        )
    except asyncio.CancelledError:
        print("\n👋 Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
