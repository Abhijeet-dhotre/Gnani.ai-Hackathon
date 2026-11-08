/*
 * FluxGarage RoboEyes for OLED Displays
 * Simplified version - centered eyes only
 */

#ifndef _ROBOEYES_SIMPLE_H
#define _ROBOEYES_SIMPLE_H

#include <Adafruit_GFX.h>

#define BGCOLOR 0
#define MAINCOLOR 1

#define DEFAULT 0
#define TIRED 1
#define ANGRY 2
#define HAPPY 3

template<typename AdafruitDisplay>
class RoboEyesSimple
{
private:
public:
  AdafruitDisplay *display;

  int screenWidth = 128;
  int screenHeight = 64;
  int frameInterval = 20;
  unsigned long fpsTimer = 0;

  bool tired = 0;
  bool angry = 0;
  bool happy = 0;

  bool eyeL_open = 1;
  bool eyeR_open = 1;

  int eyeLwidthDefault = 40;
  int eyeLheightDefault = 36;
  int eyeLwidthCurrent = eyeLwidthDefault;
  int eyeLheightCurrent = eyeLheightDefault;
  int eyeLheightNext = eyeLheightDefault;
  byte eyeLborderRadius = 10;

  int eyeRwidthDefault = 40;
  int eyeRheightDefault = 36;
  int eyeRwidthCurrent = eyeRwidthDefault;
  int eyeRheightCurrent = eyeRheightDefault;
  int eyeRheightNext = eyeRheightDefault;
  byte eyeRborderRadius = 10;

  int eyeLx, eyeLy;
  int eyeRx, eyeRy;

  int spaceBetween = 8;

  byte eyelidsTiredHeight = 0;
  byte eyelidsTiredHeightNext = 0;
  byte eyelidsAngryHeight = 0;
  byte eyelidsAngryHeightNext = 0;
  byte eyelidsHappyBottomOffset = 0;
  byte eyelidsHappyBottomOffsetNext = 0;

  bool autoblinker = 0;
  int blinkInterval = 3;
  int blinkIntervalVariation = 2;
  unsigned long blinktimer = 0;

  RoboEyesSimple(AdafruitDisplay &disp) : display(&disp) {};

  void begin(int width, int height, byte frameRate) {
    screenWidth = width;
    screenHeight = height;
    display->clearDisplay();
    display->display();
    setFramerate(frameRate);
    
    eyeLx = (screenWidth - eyeLwidthDefault - spaceBetween - eyeRwidthDefault) / 2;
    eyeLy = (screenHeight - eyeLheightDefault) / 2 - 4;
    eyeRx = eyeLx + eyeLwidthDefault + spaceBetween;
    eyeRy = eyeLy;
  }

  void update() {
    if(millis() - fpsTimer >= frameInterval) {
      drawEyes();
      fpsTimer = millis();
    }
  }

  void setFramerate(byte fps) {
    frameInterval = 1000 / fps;
  }

  void setMood(unsigned char mood) {
    tired = 0;
    angry = 0;
    happy = 0;
    
    switch (mood) {
      case TIRED: tired = 1; break;
      case ANGRY: angry = 1; break;
      case HAPPY: happy = 1; break;
    }
  }

  void setAutoblinker(bool active, int interval, int variation) {
    autoblinker = active;
    blinkInterval = interval;
    blinkIntervalVariation = variation;
  }

  void close() {
    eyeLheightNext = 1;
    eyeRheightNext = 1;
    eyeL_open = 0;
    eyeR_open = 0;
  }

  void open() {
    eyeL_open = 1;
    eyeR_open = 1;
  }

  void blink() {
    close();
    open();
  }

  void drawEyes() {
    eyeLheightCurrent = (eyeLheightCurrent + eyeLheightNext) / 2;
    eyeRheightCurrent = (eyeRheightCurrent + eyeRheightNext) / 2;

    if(eyeL_open) {
      if(eyeLheightCurrent <= 1) eyeLheightNext = eyeLheightDefault;
    }
    if(eyeR_open) {
      if(eyeRheightCurrent <= 1) eyeRheightNext = eyeRheightDefault;
    }

    eyeLwidthCurrent = eyeLwidthDefault;
    eyeRwidthCurrent = eyeRwidthDefault;

    if(autoblinker) {
      if(millis() >= blinktimer) {
        blink();
        blinktimer = millis() + (blinkInterval * 1000) + (random(blinkIntervalVariation) * 1000);
      }
    }

    display->clearDisplay();

    int eyeLyAdjusted = eyeLy + (eyeLheightDefault - eyeLheightCurrent) / 2;
    int eyeRyAdjusted = eyeRy + (eyeRheightDefault - eyeRheightCurrent) / 2;

    display->fillRoundRect(eyeLx, eyeLyAdjusted, eyeLwidthCurrent, eyeLheightCurrent, eyeLborderRadius, MAINCOLOR);
    display->fillRoundRect(eyeRx, eyeRyAdjusted, eyeRwidthCurrent, eyeRheightCurrent, eyeRborderRadius, MAINCOLOR);

    if (tired) {
      eyelidsTiredHeightNext = eyeLheightCurrent / 2;
    } else {
      eyelidsTiredHeightNext = 0;
    }

    if (angry) {
      eyelidsAngryHeightNext = eyeLheightCurrent / 2;
    } else {
      eyelidsAngryHeightNext = 0;
    }

    if (happy) {
      eyelidsHappyBottomOffsetNext = eyeLheightCurrent / 2 + 2;
    } else {
      eyelidsHappyBottomOffsetNext = 0;
    }

    eyelidsTiredHeight = (eyelidsTiredHeight + eyelidsTiredHeightNext) / 2;
    eyelidsAngryHeight = (eyelidsAngryHeight + eyelidsAngryHeightNext) / 2;
    eyelidsHappyBottomOffset = (eyelidsHappyBottomOffset + eyelidsHappyBottomOffsetNext) / 2;

    display->fillTriangle(eyeLx, eyeLyAdjusted - 1, eyeLx + eyeLwidthCurrent, eyeLyAdjusted - 1, eyeLx, eyeLyAdjusted + eyelidsTiredHeight - 1, BGCOLOR);
    display->fillTriangle(eyeRx, eyeRyAdjusted - 1, eyeRx + eyeRwidthCurrent, eyeRyAdjusted - 1, eyeRx + eyeRwidthCurrent, eyeRyAdjusted + eyelidsTiredHeight - 1, BGCOLOR);

    display->fillTriangle(eyeLx, eyeLyAdjusted - 1, eyeLx + eyeLwidthCurrent, eyeLyAdjusted - 1, eyeLx + eyeLwidthCurrent, eyeLyAdjusted + eyelidsAngryHeight - 1, BGCOLOR);
    display->fillTriangle(eyeRx, eyeRyAdjusted - 1, eyeRx + eyeRwidthCurrent, eyeRyAdjusted - 1, eyeRx, eyeRyAdjusted + eyelidsAngryHeight - 1, BGCOLOR);

    if (eyelidsHappyBottomOffset > 0) {
      display->fillRoundRect(eyeLx - 1, (eyeLyAdjusted + eyeLheightCurrent) - eyelidsHappyBottomOffset + 1, eyeLwidthCurrent + 2, eyeLheightDefault, eyeLborderRadius, BGCOLOR);
      display->fillRoundRect(eyeRx - 1, (eyeRyAdjusted + eyeRheightCurrent) - eyelidsHappyBottomOffset + 1, eyeRwidthCurrent + 2, eyeRheightDefault, eyeRborderRadius, BGCOLOR);
    }

    display->display();
  }
};

#endif