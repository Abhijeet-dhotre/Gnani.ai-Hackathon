#include <HTTPClient.h>
#include <driver/i2s.h>
#include <ArduinoJson.h>
#include <WiFiManager.h>
#include <WiFi.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "RoboEyesSimple.h"

WiFiManager wifiManager;

#define OLED_SDA    3
#define OLED_SCL    44
#define OLED_WIDTH  128
#define OLED_HEIGHT 64

Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
RoboEyesSimple<Adafruit_SSD1306> eyes(display);

volatile bool isPlayingAudio = false;
volatile unsigned long audioEndTime = 0;
uint8_t currentMood = DEFAULT;

#define TOUCH_PIN 2
#define LED_PIN   21

// Microphone (INMP441)
#define MIC_I2S_WS  4   // D3
#define MIC_I2S_SCK 5   // D4
#define MIC_I2S_SD  6   // D5

// Speaker Amplifier (MAX98357A)
// IMPORTANT: GPIO 7 = D8, GPIO 8 = D9, GPIO 9 = D10 on XIAO ESP32-S3!
#define AMP_I2S_LRC  7  // Connect LRC to pin D8
#define AMP_I2S_BCLK 8  // Connect BCLK to pin D9
#define AMP_I2S_DIN  9  // Connect DIN to pin D10
#define AMP_ENABLE   1  // Connect SD to pin D0 (or leave SD disconnected/tied to 3.3V)

#define SAMPLE_RATE     24000
#define MIC_SAMPLE_RATE 16000
#define RECORD_SECONDS  3
#define SAMPLE_SIZE     2
#define BUFFER_SIZE     (MIC_SAMPLE_RATE * RECORD_SECONDS * SAMPLE_SIZE)

#define MIC_I2S_PORT  I2S_NUM_0
#define AMP_I2S_PORT  I2S_NUM_1

uint8_t *audio_buffer;
bool lastTouchState = LOW;
bool recording = false;
int recording_position = 0;

const char* WIFI_SSID_FALLBACK = "AXR";
const char* WIFI_PASS_FALLBACK = "@bhijeet";
String server_url = "http://192.168.0.101:5050";

// Forward declarations
void animationTask(void* parameter);
void connectToWiFi();
void setupMicrophoneI2S();
void setupSpeakerI2S(int rate);
void startRecording();
void recordAudioData();
void stopRecordingAndProcess();
void sendAudioStreamed(int data_size);
void playAudioURL(String url);
void playTestBeep();
void createWavHeader(uint8_t* header, int waveDataSize, int sampleRate);

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(TOUCH_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  pinMode(AMP_ENABLE, OUTPUT);
  digitalWrite(AMP_ENABLE, HIGH); // Keep amp enabled by default for testing
  digitalWrite(LED_PIN, LOW);

  Serial.println("\n--- XIAO ESP32-S3 Robot Starting ---");

  Wire.begin(OLED_SDA, OLED_SCL);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED init failed!");
    while (1) delay(100);
  }
  Serial.println("OLED initialized");

  eyes.begin(OLED_WIDTH, OLED_HEIGHT, 50);
  eyes.setAutoblinker(true, 3, 2);
  eyes.setMood(DEFAULT);
  eyes.update();

  audio_buffer = (uint8_t*)ps_malloc(BUFFER_SIZE);
  if (audio_buffer == NULL) audio_buffer = (uint8_t*)malloc(BUFFER_SIZE);

  if (audio_buffer == NULL) {
    Serial.println("CRITICAL: Not enough RAM!");
    while (1) delay(100);
  }
  Serial.printf("Audio Buffer: %d bytes\n", BUFFER_SIZE);

  setupMicrophoneI2S();
  setupSpeakerI2S(SAMPLE_RATE);

  // Loud 2-tone startup beep to verify speaker wiring
  playTestBeep();

  connectToWiFi();

  xTaskCreatePinnedToCore(animationTask, "anim", 4096, NULL, 1, NULL, 1);

  Serial.println("Setup Complete. Touch and HOLD sensor to talk.");
}

void loop() {
  bool currentTouchState = digitalRead(TOUCH_PIN);

  if (lastTouchState == LOW && currentTouchState == HIGH) {
    delay(50);
    if (digitalRead(TOUCH_PIN) == HIGH) startRecording();
  }

  if (lastTouchState == HIGH && currentTouchState == LOW) {
    delay(50);
    if (recording) stopRecordingAndProcess();
  }

  if (recording) recordAudioData();
  lastTouchState = currentTouchState;
  delay(10);
}

void animationTask(void* parameter) {
  while (true) {
    if (isPlayingAudio && millis() < audioEndTime) {
      eyes.setMood(HAPPY);
    } else {
      isPlayingAudio = false;
      eyes.setMood(currentMood);
    }
    eyes.update();
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void connectToWiFi() {
  WiFi.mode(WIFI_STA);
  Serial.println("Connecting to WiFi...");
  wifiManager.setTimeout(180);

  if (!wifiManager.autoConnect("XIAO-Robot-Setup")) {
    Serial.println("Using fallback credentials...");
    WiFi.begin(WIFI_SSID_FALLBACK, WIFI_PASS_FALLBACK);
    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries < 20) {
      delay(500);
      Serial.print(".");
      tries++;
    }
    Serial.println();
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected! IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi connection failed!");
  }
}

void setupMicrophoneI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = MIC_SAMPLE_RATE,
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

  i2s_pin_config_t pin_config = {
    .bck_io_num = MIC_I2S_SCK,
    .ws_io_num = MIC_I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = MIC_I2S_SD
  };

  i2s_driver_install(MIC_I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(MIC_I2S_PORT, &pin_config);
  i2s_zero_dma_buffer(MIC_I2S_PORT);
}

void setupSpeakerI2S(int rate) {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = (uint32_t)rate,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 512,
    .use_apll = false,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = AMP_I2S_BCLK,
    .ws_io_num = AMP_I2S_LRC,
    .data_out_num = AMP_I2S_DIN,
    .data_in_num = I2S_PIN_NO_CHANGE
  };

  static bool installed = false;
  if (!installed) {
    i2s_driver_install(AMP_I2S_PORT, &i2s_config, 0, NULL);
    i2s_set_pin(AMP_I2S_PORT, &pin_config);
    installed = true;
  } else {
    i2s_set_clk(AMP_I2S_PORT, (uint32_t)rate, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_STEREO);
  }
  i2s_zero_dma_buffer(AMP_I2S_PORT);
}

void playTestBeep() {
  Serial.println("Playing startup test beep...");
  setupSpeakerI2S(24000);
  digitalWrite(AMP_ENABLE, HIGH);
  delay(30);

  int16_t samples[256];
  int totalFrames = 24000 / 3; // 330ms beep
  int frameIndex = 0;

  while (frameIndex < totalFrames) {
    for (int i = 0; i < 128; i++) {
      int16_t val = ((frameIndex + i) % 30 < 15) ? 8000 : -8000;
      samples[i * 2]     = val;
      samples[i * 2 + 1] = val;
    }
    size_t written = 0;
    i2s_write(AMP_I2S_PORT, samples, sizeof(samples), &written, portMAX_DELAY);
    frameIndex += 128;
  }

  delay(50);
  i2s_zero_dma_buffer(AMP_I2S_PORT);
  Serial.println("Beep finished.");
}

void startRecording() {
  recording = true;
  recording_position = 0;
  i2s_zero_dma_buffer(MIC_I2S_PORT);
  digitalWrite(LED_PIN, HIGH);
  Serial.println("Recording...");
}

void recordAudioData() {
  if (!recording) return;
  size_t bytes_read = 0;

  if (recording_position < BUFFER_SIZE) {
    int read_size = min(512, BUFFER_SIZE - recording_position);
    i2s_read(MIC_I2S_PORT, audio_buffer + recording_position, read_size, &bytes_read, portMAX_DELAY);
    recording_position += bytes_read;

    if (recording_position >= BUFFER_SIZE) {
      Serial.println("Buffer Full");
      stopRecordingAndProcess();
    }
  }
}

void stopRecordingAndProcess() {
  recording = false;
  digitalWrite(LED_PIN, LOW);
  Serial.printf("Recorded %d bytes\n", recording_position);

  int16_t* samples = (int16_t*)audio_buffer;
  int sample_count = recording_position / 2;
  for (int i = 0; i < sample_count; i++) {
    if (samples[i] > 32700) samples[i] = 32700;
    if (samples[i] < -32700) samples[i] = -32700;
  }

  sendAudioStreamed(recording_position);
}

void sendAudioStreamed(int data_size) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("No WiFi");
    return;
  }

  WiFiClient client;
  String host = server_url;
  host.replace("http://", "");
  int split = host.indexOf(':');
  String ip = host.substring(0, split);
  int port = host.substring(split + 1).toInt();

  if (!client.connect(ip.c_str(), port)) {
    Serial.println("Connection Failed");
    return;
  }

  client.setTimeout(30000);

  uint8_t wav_header[44];
  createWavHeader(wav_header, data_size, MIC_SAMPLE_RATE);

  String boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW";
  String head = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"xiao.wav\"\r\nContent-Type: audio/wav\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";

  int totalLength = head.length() + 44 + data_size + tail.length();

  client.println("POST /upload HTTP/1.1");
  client.print("Host: "); client.println(ip);
  client.println("Content-Type: multipart/form-data; boundary=" + boundary);
  client.print("Content-Length: "); client.println(totalLength);
  client.println("Connection: close");
  client.println();

  client.print(head);
  client.write(wav_header, 44);

  int sent = 0;
  while (sent < data_size) {
    int chunk = min(1024, data_size - sent);
    client.write(audio_buffer + sent, chunk);
    sent += chunk;
  }

  client.print(tail);
  Serial.println("Waiting for server response...");

  String response = "";
  bool body_started = false;
  unsigned long waitStart = millis();

  while ((client.connected() || client.available()) && (millis() - waitStart < 30000)) {
    if (client.available()) {
      String line = client.readStringUntil('\n');
      if (line == "\r") body_started = true;
      else if (body_started) response += line;
      waitStart = millis();
    } else {
      delay(5);
    }
  }
  client.stop();

  Serial.println("Raw Server Response: " + response);

  int jsonStart = response.indexOf('{');
  int jsonEnd = response.lastIndexOf('}');

  if (jsonStart != -1 && jsonEnd != -1) {
    String cleanJson = response.substring(jsonStart, jsonEnd + 1);
    DynamicJsonDocument doc(4096);
    DeserializationError error = deserializeJson(doc, cleanJson);

    if (!error) {
      String aiText = doc["ai_response"].as<String>();
      Serial.println("AI: " + aiText);

      if (doc.containsKey("emotion")) {
        String emotion = doc["emotion"].as<String>();
        if (emotion == "happy" || emotion == "excited") currentMood = HAPPY;
        else if (emotion == "sad") currentMood = TIRED;
        else if (emotion == "angry") currentMood = ANGRY;
        else currentMood = DEFAULT;
      }

      // Check both boolean true and string "true" or presence of audio_url
      bool hasAudio = doc["has_audio"].as<bool>() || doc.containsKey("audio_url");
      if (hasAudio && !doc["audio_url"].isNull()) {
        String audioPath = doc["audio_url"].as<String>();
        String full_url;

        if (audioPath.startsWith("http://") || audioPath.startsWith("https://")) {
          full_url = audioPath;
        } else {
          while (audioPath.startsWith("//")) audioPath = audioPath.substring(1);
          if (!audioPath.startsWith("/")) audioPath = "/" + audioPath;
          full_url = server_url + audioPath;
        }

        Serial.println("Audio URL: " + full_url);
        playAudioURL(full_url);
      } else {
        Serial.println("Server JSON did not include an audio_url!");
      }
    } else {
      Serial.print("JSON Error: ");
      Serial.println(error.c_str());
    }
  }
}

void playAudioURL(String url) {
  HTTPClient http;
  WiFiClient client;

  http.useHTTP10(true);
  http.setTimeout(15000);

  if (http.begin(client, url)) {
    int httpCode = http.GET();
    Serial.printf("Audio GET HTTP Code: %d\n", httpCode);

    if (httpCode == 200) {
      int len = http.getSize();
      Serial.printf("Audio Content-Length: %d\n", len);

      WiFiClient* stream = http.getStreamPtr();
      stream->setTimeout(5000);

      uint8_t first12[12];
      int got = stream->readBytes(first12, 12);
      Serial.printf("First 4 bytes: %02X %02X %02X %02X (%c%c%c%c)\n",
                    first12[0], first12[1], first12[2], first12[3],
                    isPrintable(first12[0]) ? first12[0] : '.',
                    isPrintable(first12[1]) ? first12[1] : '.',
                    isPrintable(first12[2]) ? first12[2] : '.',
                    isPrintable(first12[3]) ? first12[3] : '.');

      // Check if server accidentally sent MP3 (starts with "ID3" or 0xFF 0xFB / 0xFF 0xF3)
      if ((first12[0] == 'I' && first12[1] == 'D' && first12[2] == '3') ||
          (first12[0] == 0xFF && (first12[1] & 0xE0) == 0xE0)) {
        Serial.println("CRITICAL ERROR: Server sent an MP3 file instead of a 16-bit PCM WAV file!");
        Serial.println("Fix on Python server: Convert TTS output to 16-bit PCM WAV before sending to ESP32.");
        http.end();
        return;
      }

      uint32_t sampleRate = SAMPLE_RATE;
      uint16_t numChannels = 1;
      uint16_t bitsPerSample = 16;
      uint32_t dataSize = 0;

      if (got == 12 && memcmp(first12, "RIFF", 4) == 0 && memcmp(first12 + 8, "WAVE", 4) == 0) {
        while (stream->connected() || stream->available()) {
          uint8_t chunkHeader[8];
          if (stream->readBytes(chunkHeader, 8) < 8) break;

          uint32_t chunkSize = chunkHeader[4] | (chunkHeader[5] << 8) |
                               (chunkHeader[6] << 16) | (chunkHeader[7] << 24);

          if (memcmp(chunkHeader, "fmt ", 4) == 0) {
            uint8_t fmtData[16];
            int toRead = min((uint32_t)16, chunkSize);
            stream->readBytes(fmtData, toRead);
            numChannels   = fmtData[2] | (fmtData[3] << 8);
            sampleRate    = fmtData[4] | (fmtData[5] << 8) | (fmtData[6] << 16) | (fmtData[7] << 24);
            bitsPerSample = fmtData[14] | (fmtData[15] << 8);

            if (chunkSize > 16) {
              uint8_t dummy[32];
              int extra = chunkSize - 16;
              while (extra > 0) {
                int r = stream->readBytes(dummy, min(extra, 32));
                if (r <= 0) break;
                extra -= r;
              }
            }
          } else if (memcmp(chunkHeader, "data", 4) == 0) {
            dataSize = chunkSize;
            break;
          } else {
            uint8_t dummy[64];
            int skip = chunkSize;
            while (skip > 0) {
              int r = stream->readBytes(dummy, min(skip, 64));
              if (r <= 0) break;
              skip -= r;
            }
          }
        }
        Serial.printf("WAV Header OK -> %u Hz, %u Ch, %u Bits, DataSize: %u\n",
                      sampleRate, numChannels, bitsPerSample, dataSize);
      } else {
        Serial.println("No WAV header found — playing as raw 24kHz PCM...");
      }

      int bytesPerSecond = sampleRate * numChannels * (bitsPerSample / 8);
      unsigned long durationMs = (dataSize > 0 && bytesPerSecond > 0)
                                 ? ((unsigned long)dataSize * 1000UL / bytesPerSecond)
                                 : 4000;

      isPlayingAudio = true;
      audioEndTime = millis() + durationMs + 500;

      setupSpeakerI2S(sampleRate);
      digitalWrite(AMP_ENABLE, HIGH);
      delay(20);

      i2s_zero_dma_buffer(MIC_I2S_PORT);

      uint8_t buff[512];
      int16_t stereo[512];
      int remaining = (dataSize > 0 && dataSize < 0x7FFFFFFF)
                      ? dataSize
                      : ((len > 44) ? (len - 44) : 10000000);

      unsigned long lastDataTime = millis();
      bool hasLeftover = false;
      uint8_t leftoverByte = 0;

      while (remaining > 0 && (stream->connected() || stream->available())) {
        int avail = stream->available();
        if (avail > 0) {
          int offset = hasLeftover ? 1 : 0;
          if (hasLeftover) {
            buff[0] = leftoverByte;
            hasLeftover = false;
          }

          int maxToRead = min((int)sizeof(buff) - offset, remaining);
          int toRead = min(avail, maxToRead);
          int bytesRead = stream->read(buff + offset, toRead);

          if (bytesRead > 0) {
            lastDataTime = millis();
            remaining -= bytesRead;
            int totalBytes = bytesRead + offset;

            if (totalBytes % 2 != 0) {
              leftoverByte = buff[totalBytes - 1];
              hasLeftover = true;
              totalBytes--;
            }

            if (totalBytes > 0) {
              size_t written = 0;
              if (numChannels == 1) {
                int samples = totalBytes / 2;
                int16_t* mono = (int16_t*)buff;
                for (int i = 0; i < samples; i++) {
                  stereo[i * 2]     = mono[i];
                  stereo[i * 2 + 1] = mono[i];
                }
                i2s_write(AMP_I2S_PORT, stereo, samples * 4, &written, portMAX_DELAY);
              } else {
                i2s_write(AMP_I2S_PORT, buff, totalBytes, &written, portMAX_DELAY);
              }
            }
          }
        } else {
          if (millis() - lastDataTime > 3000) {
            Serial.println("Stream timeout!");
            break;
          }
          delay(2);
        }
      }

      delay(150);
      Serial.println("Playback Complete!");
    } else {
      Serial.printf("HTTP GET failed, code: %d\n", httpCode);
    }
  } else {
    Serial.println("Failed to connect to audio URL");
  }

  http.end();
  i2s_zero_dma_buffer(AMP_I2S_PORT);
  isPlayingAudio = false;
}

void createWavHeader(uint8_t* header, int waveDataSize, int sampleRate) {
  int fileSize = waveDataSize + 36;
  memcpy(header, "RIFF", 4);
  *(int32_t*)(header + 4) = fileSize;
  memcpy(header + 8, "WAVEfmt ", 8);
  *(int32_t*)(header + 16) = 16;
  *(int16_t*)(header + 20) = 1;
  *(int16_t*)(header + 22) = 1;
  *(int32_t*)(header + 24) = sampleRate;
  *(int32_t*)(header + 28) = sampleRate * 2;
  *(int16_t*)(header + 32) = 2;
  *(int16_t*)(header + 34) = 16;
  memcpy(header + 36, "data", 4);
  *(int32_t*)(header + 40) = waveDataSize;
}