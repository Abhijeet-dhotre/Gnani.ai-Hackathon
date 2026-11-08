// INMP441 MICROPHONE TEST — standalone, no WiFi, no speaker, no server.
//
// WHAT TO DO:
//   1. Upload this sketch to the XIAO ESP32-S3.
//   2. Open Serial Monitor at 115200 baud.
//   3. Speak NORMALLY close to the mic. Watch the numbers:
//
// HOW TO READ IT:
//   rms=0, peak=0       -> mic sends NOTHING. Wiring/power problem (see below)
//   rms ~1-99           -> too quiet. Check mic orientation (hole faces mouth)
//   rms 100-2000        -> normal speech. Mic is FINE, problem is elsewhere
//   rms >4000 or peak ~ -32768/32767 nonstop -> garbage/alignment (check L/R pin!)
//
// WIRING (INMP441 -> XIAO ESP32-S3):
//   VCC -> 3.3V      (NEVER 5V — INMP441 max is 3.6V!)
//   GND -> GND
//   L/R -> GND       (LEFT channel = what this sketch reads. If L/R is
//                     3.3V or floating, the left slot reads ZEROS forever)
//   WS  -> GPIO4
//   SCK -> GPIO5
//   SD  -> GPIO6

#include <Arduino.h>
#include <driver/i2s.h>

#define MIC_I2S_WS  4
#define MIC_I2S_SCK 5
#define MIC_I2S_SD  6

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== INMP441 MIC TEST — speak now, watch rms/peak ===");

  i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num = MIC_I2S_SCK,
    .ws_io_num = MIC_I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = MIC_I2S_SD
  };
  i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pins);
  i2s_zero_dma_buffer(I2S_NUM_0);
}

void loop() {
  static int16_t buf[512];
  size_t n = 0;
  i2s_read(I2S_NUM_0, buf, sizeof(buf), &n, portMAX_DELAY);
  if (n == 0) return;

  int count = n / 2;
  int64_t sum = 0;
  int16_t mn = 32767, mx = -32768;
  for (int i = 0; i < count; i++) {
    sum += (int32_t)buf[i] * buf[i];
    if (buf[i] < mn) mn = buf[i];
    if (buf[i] > mx) mx = buf[i];
  }
  double rms = sqrt((double)(sum / count));

  static int silentRun = 0;
  if ((int)rms == 0) silentRun++;

  Serial.printf("rms=%5.0f peak=%6d range=[%d..%d] %s\n",
                rms, mx, mn, mx,
                (rms < 30) ? "<- SILENT" : (rms > 4000 ? "<- GARBAGE?" : "<- ok"));

  if (silentRun == 20) {
    Serial.println("\n!!! 10 seconds of pure ZEROS. Fix hardware: L/R pin must go ");
    Serial.println("!!! to GND, VCC to 3.3V, and check WS=4 SCK=5 SD=6 aren't crossed.");
  }
  delay(50);
}
