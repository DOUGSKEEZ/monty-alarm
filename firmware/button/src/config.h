// ===================================================================================
// User Configurations for the Monty alarm buttons (1key_XGM board, CH552E)
// ===================================================================================
//
// Pin map traced with a multimeter on 2026-10-19:
// P1.4 (pin 1) - key switch to GND (active low)
// P1.5 (pin 2) - addressable LED data-in, through R3
// P1.6, P1.7   - not connected

#pragma once

// Pin definitions
#define PIN_KEY             P14       // pin connected to the key switch
#define PIN_NEO             P15       // pin connected to the addressable LED

// NeoPixel configuration
#define NEO_GRB                       // type of pixel: NEO_GRB or NEO_RGB

// Firmware version, reported by the GET_INFO request
#define FW_VERSION_MAJOR    1
#define FW_VERSION_MINOR    0

// USB device descriptor
#define USB_VENDOR_ID       0x1209    // VID (pid.codes)
#define USB_PRODUCT_ID      0x0001    // PID (pid.codes test PID, private use only)
#define USB_DEVICE_VERSION  0x0100    // v1.0 (BCD-format)

// USB configuration descriptor
#define USB_MAX_POWER_mA    100       // max power in mA (MCU plus LED at full white)

// USB descriptor strings
#define MANUFACTURER_STR    'M','o','n','t','y'
#define PRODUCT_STR         'M','o','n','t','y',' ','A','l','a','r','m',' ','B','u','t','t','o','n'
#define SERIAL_STR          'C','H','5','5','2','E'
#define INTERFACE_STR       'H','I','D','-','K','e','y','b','o','a','r','d'
