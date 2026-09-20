// Streams accelerometer + gyro samples at a steady 64 Hz as CSV, for recording on the laptop
// and checking with analysis/src/check_recording.py. No detection here yet.
//
// NOT YET COMPILED OR RUN: written from bringup/GyroTestCodeWorking.ino (which is known to
// work on the UNO Q) plus the MPU register map. Check the first capture with
// check_recording.py before trusting it.
//
// Output, one row per sample:
//     t_us,ax_mg,ay_mg,az_mg,gx_dps,gy_dps,gz_dps
// Lines starting with '#' are comments/status and are ignored by the checker.

#include <Wire.h>

// Sensor on A4 (SDA) / A5 (SCL), which is the Wire2 bus on the UNO Q.
#define IMU_WIRE  Wire2

#define MPU_ADDRESS            0x68   // AD0 low; 0x69 if AD0 is high
#define MPU_RA_SMPLRT_DIV      0x19
#define MPU_RA_CONFIG          0x1A
#define MPU_RA_GYRO_CONFIG     0x1B
#define MPU_RA_ACCEL_CONFIG    0x1C
#define MPU_RA_ACCEL_CONFIG2   0x1D   // MPU6500/9250/9255 only
#define MPU_RA_ACCEL_XOUT_H    0x3B
#define MPU_RA_PWR_MGMT_1      0x6B
#define MPU_RA_WHO_AM_I        0x75
#define MPU_PWR1_SLEEP         0x40

// +-8 g: heel strikes reach 4-5 g in both patient datasets, so the default +-2 g would clip.
// +-2000 deg/s: shank swing reached ~740 deg/s in the Mendeley data.
#define ACCEL_CONFIG_8G        0x10
#define GYRO_CONFIG_2000DPS    0x18
#define DLPF_20HZ              0x04   // ~20 Hz low-pass, anti-aliasing for 64 Hz sampling
const float ACC_MG_PER_LSB   = 1000.0f / 4096.0f;   // 4096 LSB/g at +-8 g
const float GYRO_DPS_PER_LSB = 1.0f / 16.4f;        // 16.4 LSB/(deg/s) at +-2000 deg/s

// The detector assumes exactly 64 Hz: 1,000,000 / 64 = 15625 us.
const uint32_t SAMPLE_PERIOD_US = 15625;

// Each Serial.print() on the UNO Q is sent to the Linux side as one message, so rows are
// sent in batches. If check_recording.py reports missed samples, try a different size.
#define ROWS_PER_MESSAGE  8

uint32_t nextSampleUs;
uint32_t samplesSent = 0;
uint32_t samplesMissed = 0;   // scheduler slots skipped because the loop was busy
uint32_t readErrors = 0;
uint32_t sensorResets = 0;
int chipId = -1;
String batch;
uint8_t rowsInBatch = 0;

bool writeReg(uint8_t reg, uint8_t value)
{
    IMU_WIRE.beginTransmission(MPU_ADDRESS);
    IMU_WIRE.write(reg);
    IMU_WIRE.write(value);
    return IMU_WIRE.endTransmission() == 0;
}

bool readRegs(uint8_t reg, uint8_t length, uint8_t *data)
{
    IMU_WIRE.beginTransmission(MPU_ADDRESS);
    IMU_WIRE.write(reg);
    if (IMU_WIRE.endTransmission() != 0) return false;
    if (IMU_WIRE.requestFrom((uint8_t)MPU_ADDRESS, (size_t)length) != length) return false;
    for (uint8_t i = 0; i < length; i++) data[i] = IMU_WIRE.read();
    return true;
}

int readReg(uint8_t reg)
{
    uint8_t value;
    return readRegs(reg, 1, &value) ? value : -1;
}

void initIMU()
{
    writeReg(MPU_RA_PWR_MGMT_1, 0x01);                  // wake up, clock from the X gyro PLL
    delay(50);
    writeReg(MPU_RA_CONFIG, DLPF_20HZ);                 // low-pass (accel + gyro on MPU6050, gyro on 6500/9250)
    writeReg(MPU_RA_SMPLRT_DIV, 0x00);                  // chip updates at 1 kHz; we pick samples at 64 Hz
    writeReg(MPU_RA_GYRO_CONFIG, GYRO_CONFIG_2000DPS);
    writeReg(MPU_RA_ACCEL_CONFIG, ACCEL_CONFIG_8G);
    // WHO_AM_I: 0x68 = MPU6050/9150, 0x70 = MPU6500, 0x71 = MPU9250, 0x73 = MPU9255.
    // The newer chips have a separate accel low-pass register.
    chipId = readReg(MPU_RA_WHO_AM_I);
    if (chipId == 0x70 || chipId == 0x71 || chipId == 0x73) {
        writeReg(MPU_RA_ACCEL_CONFIG2, DLPF_20HZ);
    }
    delay(50);
}

// The chip powers up asleep. If it is ever found asleep it has reset (usually a brief power
// loss from a loose wire) and has also lost its range settings, so configure it again.
void checkSensorAwake()
{
    int pwr = readReg(MPU_RA_PWR_MGMT_1);
    if (pwr >= 0 && (pwr & MPU_PWR1_SLEEP)) {
        initIMU();
        sensorResets++;
    }
}

void setup()
{
    IMU_WIRE.begin();   // default 100 kHz, as in the bring-up sketch; a 14-byte read takes ~2 ms
    Serial.begin(115200);
    initIMU();

    batch.reserve(ROWS_PER_MESSAGE * 56 + 16);
    String header = "# imu_stream 64 Hz, acc +-8 g in mg, gyro +-2000 dps, who_am_i=0x";
    header += String(chipId, HEX);
    header += "\nt_us,ax_mg,ay_mg,az_mg,gx_dps,gy_dps,gz_dps\n";
    Serial.print(header);

    nextSampleUs = micros() + SAMPLE_PERIOD_US;
}

void loop()
{
    uint32_t now = micros();
    if ((int32_t)(now - nextSampleUs) < 0) return;      // not time yet (safe across micros() wrap)

    // If we are more than one period late, skip the lost slots rather than bunching samples up.
    uint32_t late = now - nextSampleUs;
    if (late >= SAMPLE_PERIOD_US) {
        uint32_t skipped = late / SAMPLE_PERIOD_US;
        samplesMissed += skipped;
        nextSampleUs += skipped * SAMPLE_PERIOD_US;
    }
    nextSampleUs += SAMPLE_PERIOD_US;

    uint8_t raw[14];   // accel (6), temperature (2), gyro (6) in one read
    uint32_t stamp = micros();
    if (!readRegs(MPU_RA_ACCEL_XOUT_H, 14, raw)) {
        readErrors++;
        return;
    }
    int16_t ax = ((int16_t)raw[0] << 8) | raw[1];
    int16_t ay = ((int16_t)raw[2] << 8) | raw[3];
    int16_t az = ((int16_t)raw[4] << 8) | raw[5];
    int16_t gx = ((int16_t)raw[8] << 8) | raw[9];
    int16_t gy = ((int16_t)raw[10] << 8) | raw[11];
    int16_t gz = ((int16_t)raw[12] << 8) | raw[13];

    batch += stamp;                                   batch += ',';
    batch += String(ax * ACC_MG_PER_LSB, 1);          batch += ',';
    batch += String(ay * ACC_MG_PER_LSB, 1);          batch += ',';
    batch += String(az * ACC_MG_PER_LSB, 1);          batch += ',';
    batch += String(gx * GYRO_DPS_PER_LSB, 1);        batch += ',';
    batch += String(gy * GYRO_DPS_PER_LSB, 1);        batch += ',';
    batch += String(gz * GYRO_DPS_PER_LSB, 1);        batch += '\n';
    samplesSent++;

    if (++rowsInBatch >= ROWS_PER_MESSAGE) {
        // Once a second: health check and a status line.
        if (samplesSent % 64 < ROWS_PER_MESSAGE) {
            checkSensorAwake();
            batch += "# sent=";     batch += samplesSent;
            batch += " missed=";    batch += samplesMissed;
            batch += " i2c_errors="; batch += readErrors;
            batch += " resets=";    batch += sensorResets;
            batch += '\n';
        }
        Serial.print(batch);
        batch = "";
        rowsInBatch = 0;
    }
}
