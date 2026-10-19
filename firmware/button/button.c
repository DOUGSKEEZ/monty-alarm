// ===================================================================================
// Project:   Monty alarm button firmware for the CH552E one-key pads (1key_XGM board)
// Version:   v1.0
// Year:      2026
// Based on:  CAPS bLOCK by Stefan Wagner, https://github.com/wagiminator
// License:   http://creativecommons.org/licenses/by-sa/3.0/
// ===================================================================================
//
// Description:
// ------------
// Replaces the factory firmware of the alarm's two USB buttons. The pad is a plain
// boot keyboard that sends "a" while the key is held, so the Pi's button handler
// works unchanged. The Pi sets the LED with USB vendor requests on EP0; it starts
// off at power-up (after a short dim blink that shows the firmware is alive).
//
// Vendor requests (bmRequestType 0x40 host-to-device, 0xC0 device-to-host):
// - 0x10 SET_LED:    wValue = R | G<<8, wIndex = B | mode<<8, no data
//                    mode 0 = solid, 1 = breathe, 2 = slow blink, 3 = fast blink
// - 0x11 GET_INFO:   returns 8 bytes: 'M', major, minor, R, G, B, mode, key down
// - 0x1B BOOTLOADER: detach and jump to the WCH USB bootloader (4348:55e0) so the
//                    next firmware can be flashed without opening the pad
//
// Compilation Instructions:
// -------------------------
// - Chip:  CH552E, 16 MHz internal clock
// - Run 'make bin' with SDCC installed.
// - Flash with 'wchisp flash button.bin' while the pad is in bootloader mode.

// ===================================================================================
// Libraries, Definitions and Macros
// ===================================================================================

// Libraries
#include "src/config.h"                   // user configurations
#include "src/system.h"                   // system functions
#include "src/gpio.h"                     // GPIO functions
#include "src/delay.h"                    // delay functions
#include "src/neo.h"                      // NeoPixel functions
#include "src/usb.h"                      // USB request definitions
#include "src/usb_hid.h"                  // USB HID functions
#include "src/usb_handler.h"              // USB handler and EP0 buffer

// Vendor requests
#define REQ_SET_LED         0x10
#define REQ_GET_INFO        0x11
#define REQ_BOOTLOADER      0x1B

// LED modes
#define MODE_SOLID          0
#define MODE_BREATHE        1
#define MODE_BLINK_SLOW     2
#define MODE_BLINK_FAST     3

#define DEBOUNCE_MS         5             // key must be stable this long
#define HID_KEY_A           0x04          // HID usage ID of the "a" key

// Prototypes for used interrupts
void USB_interrupt(void);
void USB_ISR(void) __interrupt(INT_NO_USB) {
  USB_interrupt();
}

// LED request from the host, written in the USB interrupt
volatile uint8_t req_r, req_g, req_b, req_mode;
volatile __bit req_changed = 0;
volatile __bit boot_requested = 0;

__bit key_down = 0;                       // debounced key state
__xdata uint8_t KBD_report[8] = {0,0,0,0,0,0,0,0};

// ===================================================================================
// EP0 Class and Vendor Requests (called from the USB interrupt)
// ===================================================================================
// Returns the number of bytes to send back, or 0xFF to stall.
#pragma save
#pragma nooverlay
uint8_t BTN_control(void) {
  uint8_t len;
  if((USB_setupBuf->bRequestType & USB_REQ_TYP_MASK) == USB_REQ_TYP_VENDOR) {
    switch(SetupReq) {
      case REQ_SET_LED:
        req_r    = USB_setupBuf->wValueL;
        req_g    = USB_setupBuf->wValueH;
        req_b    = USB_setupBuf->wIndexL;
        req_mode = USB_setupBuf->wIndexH;
        req_changed = 1;
        return 0;

      case REQ_GET_INFO:                  // EP0_buffer holds the setup packet until here
        EP0_buffer[0] = 'M';
        EP0_buffer[1] = FW_VERSION_MAJOR;
        EP0_buffer[2] = FW_VERSION_MINOR;
        EP0_buffer[3] = req_r;
        EP0_buffer[4] = req_g;
        EP0_buffer[5] = req_b;
        EP0_buffer[6] = req_mode;
        EP0_buffer[7] = key_down;
        len = 8;
        break;

      case REQ_BOOTLOADER:
        boot_requested = 1;               // main loop detaches after the status stage
        return 0;

      default:
        return 0xFF;
    }
  }
  else {                                  // HID class requests
    switch(SetupReq) {
      case HID_SET_IDLE:
      case HID_SET_PROTOCOL:
        return 0;

      case HID_GET_IDLE:
        EP0_buffer[0] = 0;
        len = 1;
        break;

      case HID_GET_PROTOCOL:
        EP0_buffer[0] = 1;                // report protocol
        len = 1;
        break;

      case HID_GET_REPORT:
        for(len = 0; len < 8; len++) EP0_buffer[len] = KBD_report[len];
        break;

      default:                            // SET_REPORT goes to EP2 OUT instead
        return 0xFF;
    }
  }
  if(SetupLen < len) len = SetupLen;      // never send more than the host asked for
  return len;
}
#pragma restore

// ===================================================================================
// LED Functions
// ===================================================================================
uint8_t shown_r = 1, shown_g = 1, shown_b = 1;  // forces the first write

// Write a color to the LED if it differs from what's shown
void LED_show(uint8_t r, uint8_t g, uint8_t b) {
  if(r == shown_r && g == shown_g && b == shown_b) return;
  NEO_writeColor(r, g, b);
  NEO_latch();
  shown_r = r; shown_g = g; shown_b = b;
}

// Scale a color channel by level (0..255)
uint8_t LED_scale(uint8_t c, uint8_t level) {
  return ((uint16_t)c * level) >> 8;
}

// ===================================================================================
// Main Function
// ===================================================================================
void main(void) {
  // LED settings currently in effect (copied from the request)
  uint8_t r = 0, g = 0, b = 0, mode = MODE_SOLID;
  uint16_t phase = 0;                     // effect position in ms
  uint8_t level;                          // effect brightness
  uint8_t debounce = 0;                   // ms the raw key has differed from key_down
  __bit pressed;                          // raw key state
  __bit sent_down = 0;                    // key state last reported to the host

  // Setup
  CLK_config();                           // configure system clock
  DLY_ms(10);                             // wait for clock to settle
  NEO_init();                             // init LED pin
  LED_show(0, 0, 0);                      // LED off as early as possible
  PIN_input_PU(PIN_KEY);                  // key pulls the pin to GND
  HID_init();                             // init USB HID keyboard

  LED_show(0, 12, 0);                     // short dim green blink: firmware alive
  DLY_ms(300);
  LED_show(0, 0, 0);

  WDT_start();                            // restart if the loop ever hangs (~1 s)

  // Loop, about once per ms
  while(1) {
    WDT_reset();
    DLY_ms(1);

    // Debounce the key
    pressed = !PIN_read(PIN_KEY);
    if(pressed != key_down) {
      if(++debounce >= DEBOUNCE_MS) {
        key_down = pressed;
        debounce = 0;
      }
    }
    else debounce = 0;

    // Report key changes without blocking: the host may not be polling yet
    if(key_down != sent_down && UsbConfig && !HID_EP1_writeBusyFlag) {
      sent_down = key_down;
      KBD_report[2] = sent_down ? HID_KEY_A : 0;
      HID_sendReport(KBD_report, sizeof(KBD_report));
    }

    // Take over a new LED request
    if(req_changed) {
      EA = 0;
      r = req_r; g = req_g; b = req_b; mode = req_mode;
      req_changed = 0;
      EA = 1;
      phase = 0;
    }

    // Run the LED effect
    switch(mode) {
      case MODE_BREATHE:                  // 2.56 s period, 5 ms steps
        if(++phase >= 2560) phase = 0;
        if(phase % 5) break;
        level = phase < 1280 ? phase / 5 : (2559 - phase) / 5;
        level = LED_scale(level, level);  // rough gamma so the low end fades slowly
        LED_show(LED_scale(r, level), LED_scale(g, level), LED_scale(b, level));
        break;

      case MODE_BLINK_SLOW:               // 1 s on, 1 s off
      case MODE_BLINK_FAST:               // 125 ms on, 125 ms off
        if(++phase >= (mode == MODE_BLINK_SLOW ? 2000 : 250)) phase = 0;
        if(phase < (mode == MODE_BLINK_SLOW ? 1000 : 125)) LED_show(r, g, b);
        else LED_show(0, 0, 0);
        break;

      default:                            // solid, including off
        LED_show(r, g, b);
        break;
    }

    // Jump to the bootloader when the host asked for it
    if(boot_requested) {
      DLY_ms(20);                         // let the control transfer finish
      WDT_stop();                         // the bootloader doesn't feed the watchdog
      LED_show(0, 0, 0);
      UDEV_CTRL = 0;                      // detach so the host sees a disconnect
      USB_CTRL  = 0;
      DLY_ms(100);
      BOOT_now();
    }
  }
}
